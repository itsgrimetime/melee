"""Lifetime/layout pressure attribution for source-shape probes."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .colorgraph_parser import find_function, parse_hook_events
from .parser import Function, Pass, parse_pcdump
from .simplify_search import baseline_signature
from .source_spans import StatementSpan, list_statement_spans
from .virtual_attribution import explain_virtuals


@dataclass(frozen=True)
class TargetPairState:
    virtual: int
    other_virtual: int
    colorgraph_interference: bool
    live_overlap: bool
    same_assigned_reg: bool | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "virtual": self.virtual,
            "other_virtual": self.other_virtual,
            "colorgraph_interference": self.colorgraph_interference,
            "live_overlap": self.live_overlap,
            "same_assigned_reg": self.same_assigned_reg,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PairDelta:
    before: TargetPairState
    after: TargetPairState

    @property
    def improved(self) -> bool:
        return (
            self.before.colorgraph_interference
            and not self.after.colorgraph_interference
        ) or (
            self.before.live_overlap
            and not self.after.live_overlap
        )

    def to_dict(self) -> dict:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "improved": self.improved,
        }


@dataclass(frozen=True)
class PressureSignature:
    frame_size: int | None
    saved_regs: tuple[str, ...]
    spill_set: tuple[int, ...]
    interference_edges: tuple[tuple[int, int], ...]
    coalesce_mappings: tuple[tuple[int, int], ...]
    target_pairs: tuple[TargetPairState, ...]

    def to_dict(self) -> dict:
        return {
            "frame_size": self.frame_size,
            "saved_regs": list(self.saved_regs),
            "spill_set": list(self.spill_set),
            "interference_edges": [list(edge) for edge in self.interference_edges],
            "coalesce_mappings": [list(pair) for pair in self.coalesce_mappings],
            "target_pairs": [pair.to_dict() for pair in self.target_pairs],
        }


@dataclass(frozen=True)
class PressureDelta:
    frame_before: int | None
    frame_after: int | None
    frame_delta: int | None
    saved_added: tuple[str, ...]
    saved_removed: tuple[str, ...]
    spill_added: tuple[int, ...]
    spill_removed: tuple[int, ...]
    interference_added: tuple[tuple[int, int], ...]
    interference_removed: tuple[tuple[int, int], ...]
    coalesce_added: tuple[tuple[int, int], ...]
    coalesce_removed: tuple[tuple[int, int], ...]
    target_pairs: tuple[PairDelta, ...]

    def to_dict(self) -> dict:
        return {
            "frame_before": self.frame_before,
            "frame_after": self.frame_after,
            "frame_delta": self.frame_delta,
            "saved_added": list(self.saved_added),
            "saved_removed": list(self.saved_removed),
            "spill_added": list(self.spill_added),
            "spill_removed": list(self.spill_removed),
            "interference_added": [
                list(edge) for edge in self.interference_added
            ],
            "interference_removed": [
                list(edge) for edge in self.interference_removed
            ],
            "coalesce_added": [list(pair) for pair in self.coalesce_added],
            "coalesce_removed": [list(pair) for pair in self.coalesce_removed],
            "target_pairs": [pair.to_dict() for pair in self.target_pairs],
        }


@dataclass(frozen=True)
class LifetimeLayoutProbe:
    label: str
    operator: str
    description: str
    source_text: str
    provenance: dict | None = None

    def to_dict(self, *, include_source: bool = False) -> dict:
        data = {
            "label": self.label,
            "operator": self.operator,
            "description": self.description,
        }
        if self.provenance is not None:
            data["provenance"] = self.provenance
        if include_source:
            data["source_text"] = self.source_text
        return data


_FRAME_RE = re.compile(r"\br1\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)")
_STMW_RE = re.compile(r"\br(\d+)\s*,")
_STW_RE = re.compile(r"\br(\d+)\s*,\s*[-+]?(?:0x[0-9A-Fa-f]+|\d+)\s*\(\s*r1\s*\)")
_STFD_RE = re.compile(r"\bf(\d+)\s*,\s*[-+]?(?:0x[0-9A-Fa-f]+|\d+)\s*\(\s*r1\s*\)")
_LOCAL_DECL_RE = re.compile(
    r"^[ \t]*(?:const\s+|volatile\s+)*"
    r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
    r"(?:\s*\*)*\s+([A-Za-z_]\w*)"
    r"(?:\s*\[[^\]]*\])*"
    r"\s*(?:=\s*[^;]*)?;\s*$"
)
_DECL_LINE_RE = re.compile(
    r"^([ \t]*)(int|s32|u32|float|double|[A-Za-z_]\w+(?:\s*\*)?)"
    r"\s+([A-Za-z_]\w*)\s*;\n?$"
)
_MEMBER_EXPR_RE = (
    r"[A-Za-z_]\w*\s*(?:->|\.)\s*[A-Za-z_]\w*"
)
_DIFF_EXPR_RE = (
    rf"{_MEMBER_EXPR_RE}\s*-\s*{_MEMBER_EXPR_RE}"
)
_SIMPLE_LOCAL_DECL_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<type>(?:const\s+)?[A-Za-z_]\w*(?:\s*\*)*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expr>.+);\s*$",
    re.DOTALL,
)
_SIMPLE_LOCAL_BARE_DECL_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<type>(?:const\s+)?[A-Za-z_]\w*(?:\s*\*)*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*;\s*$",
    re.DOTALL,
)
_SIMPLE_ASSIGN_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expr>.+);\s*$",
    re.DOTALL,
)
_SIMPLE_CALL_STMT_RE = re.compile(
    r"^(?P<indent>\s*)(?P<callee>[A-Za-z_]\w*)\s*\(",
    re.DOTALL,
)
_SIMPLE_RHS_ASSIGN_USE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>[A-Za-z_]\w*)\s*;\s*$",
    re.DOTALL,
)
_DEMATERIALIZE_SCALAR_TYPES = {
    "BOOL",
    "bool",
    "char",
    "double",
    "f32",
    "f64",
    "float",
    "int",
    "long",
    "s8",
    "s16",
    "s32",
    "s64",
    "short",
    "u8",
    "u16",
    "u32",
    "u64",
    "unsigned",
}

SOURCE_LIFETIME_TARGETED_OPERATORS = (
    "for-condition-field-reload",
    "repeated-helper-result-reuse",
    "helper-result-dematerialize",
    "simple-helper-inline-body",
)

SOURCE_LIFETIME_GENERIC_OPERATORS = (
    "declaration-order",
    "loop-counter-hoist",
    "loop-counter-type",
    "temp-introduction",
    "temp-removal",
    "declaration-use-distance",
    "block-scope",
    "call-argument-tempization",
    "expression-shape",
)

HELPER_INLINE_LIFETIME_OPERATORS = (
    *SOURCE_LIFETIME_TARGETED_OPERATORS,
    *SOURCE_LIFETIME_GENERIC_OPERATORS,
)

_READ_ONLY_SOURCE_LIFETIME_HELPERS = frozenset({"fn_803AC634"})


def pressure_signature_from_pcdump(
    pcdump_text: str,
    function: str,
    *,
    pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
    class_id: int = 0,
) -> PressureSignature:
    """Extract pressure-relevant allocator/prologue facts for one function."""
    events = find_function(parse_hook_events(pcdump_text), function)
    parsed = parse_pcdump(pcdump_text, function=function)
    if events is None and not parsed:
        raise ValueError(f"{function} not found in pcdump")
    if events is not None:
        sig = baseline_signature(events, class_id=class_id)
        spill_set = tuple(sorted(_spilled_markers(events)))
        interference_edges = tuple(sorted(sig.interference_edges))
        coalesce_mappings = tuple(sorted(sig.coalesce_mappings))
    else:
        spill_set = ()
        interference_edges = ()
        coalesce_mappings = ()

    fn = parsed[0] if parsed else None
    frame_size, saved_regs = _frame_and_saved_regs(fn)
    pair_states = _target_pair_states(pcdump_text, function, pairs)
    return PressureSignature(
        frame_size=frame_size,
        saved_regs=saved_regs,
        spill_set=spill_set,
        interference_edges=interference_edges,
        coalesce_mappings=coalesce_mappings,
        target_pairs=pair_states,
    )


def _spilled_markers(events) -> set[int]:
    """All simplifygraph SPILLED markers, matching inspect/stuck reporting."""
    spilled: set[int] = set()
    for section in events.simplify_sections:
        for entry in section.entries:
            if entry.spilled and entry.ig_idx >= 0:
                spilled.add(entry.ig_idx)
    return spilled


def compare_pressure_signatures(
    baseline: PressureSignature,
    candidate: PressureSignature,
) -> PressureDelta:
    frame_delta = None
    if baseline.frame_size is not None and candidate.frame_size is not None:
        frame_delta = candidate.frame_size - baseline.frame_size

    saved_before = set(baseline.saved_regs)
    saved_after = set(candidate.saved_regs)
    spill_before = set(baseline.spill_set)
    spill_after = set(candidate.spill_set)
    ig_before = set(baseline.interference_edges)
    ig_after = set(candidate.interference_edges)
    co_before = set(baseline.coalesce_mappings)
    co_after = set(candidate.coalesce_mappings)
    pair_after = {
        (pair.virtual, pair.other_virtual): pair
        for pair in candidate.target_pairs
    }
    pair_deltas = []
    for before in baseline.target_pairs:
        after = pair_after.get((before.virtual, before.other_virtual))
        if after is None:
            continue
        pair_deltas.append(PairDelta(before=before, after=after))
    return PressureDelta(
        frame_before=baseline.frame_size,
        frame_after=candidate.frame_size,
        frame_delta=frame_delta,
        saved_added=tuple(sorted(saved_after - saved_before)),
        saved_removed=tuple(sorted(saved_before - saved_after)),
        spill_added=tuple(sorted(spill_after - spill_before)),
        spill_removed=tuple(sorted(spill_before - spill_after)),
        interference_added=tuple(sorted(ig_after - ig_before)),
        interference_removed=tuple(sorted(ig_before - ig_after)),
        coalesce_added=tuple(sorted(co_after - co_before)),
        coalesce_removed=tuple(sorted(co_before - co_after)),
        target_pairs=tuple(pair_deltas),
    )


def render_pressure_delta(
    label: str,
    operator: str,
    delta: PressureDelta,
) -> str:
    lines = [f"- {label} [{operator}]"]
    if delta.frame_delta is None:
        lines.append("  frame: unchanged/unknown")
    else:
        sign = "+" if delta.frame_delta > 0 else ""
        lines.append(
            f"  frame: {delta.frame_before} -> {delta.frame_after} "
            f"({sign}{delta.frame_delta})"
        )
    lines.append(
        "  saved: "
        f"+{_fmt_regs(delta.saved_added)} -{_fmt_regs(delta.saved_removed)}"
    )
    lines.append(
        "  spill: "
        f"+{_fmt_ints(delta.spill_added)} -{_fmt_ints(delta.spill_removed)}"
    )
    lines.append(
        "  interference: "
        f"+{len(delta.interference_added)} -{len(delta.interference_removed)}"
    )
    lines.append(
        "  coalesce: "
        f"+{len(delta.coalesce_added)} -{len(delta.coalesce_removed)}"
    )
    for pair in delta.target_pairs:
        before = "yes" if pair.before.colorgraph_interference else "no"
        after = "yes" if pair.after.colorgraph_interference else "no"
        marker = " improved" if pair.improved else ""
        lines.append(
            f"  target r{pair.before.virtual}/r{pair.before.other_virtual}: "
            f"interference {before}->{after}; "
            f"live {pair.before.live_overlap}->{pair.after.live_overlap}"
            f"{marker}"
        )
    return "\n".join(lines)


def generate_lifetime_layout_probes(
    source_text: str,
    function: str,
    *,
    frame_reservation_bytes: int | None = None,
    max_probes: int = 12,
    operator_filter: Iterable[str] | None = None,
) -> list[LifetimeLayoutProbe]:
    """Generate conservative source-shape probes for pressure exploration.

    These are intentionally simple, mechanical variants. The command that
    consumes them compiles and scores the pressure effect; this generator only
    provides representative actuators for each operator family.
    """
    span = _find_function_body_span(source_text, function)
    if span is None:
        return []
    body_start, body_end = span
    body = source_text[body_start:body_end]
    probes: list[LifetimeLayoutProbe] = []

    if frame_reservation_bytes is not None and frame_reservation_bytes > 0:
        _append_probe(
            probes,
            _probe_frame_reservation_pad_stack(
                source_text,
                body,
                body_start,
                frame_reservation_bytes,
            ),
        )
    for probe in _probe_call_return_compare_chain(
        source_text,
        body,
        body_start,
        body_end,
        function,
    ):
        _append_probe(probes, probe)
    for probe in _probe_expression_shape(source_text, body, body_start, function):
        _append_probe(probes, probe)
    for probe in _probe_declaration_order(source_text, body, body_start, function):
        _append_probe(probes, probe)
    for probe in _probe_indexed_pointer_loop(source_text, body, body_start, function):
        _append_probe(probes, probe)
    for probe in _probe_pointer_walk_loop(source_text, body, body_start, function):
        _append_probe(probes, probe)
    for probe in _probe_pointer_base_call_loop(source_text, body, body_start, function):
        _append_probe(probes, probe)
    _append_probe(
        probes,
        _probe_temp_introduction(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_temp_removal(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_type_width(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_declaration_use_distance(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_boolean_guard_switch(source_text, body, body_start, body_end, function),
    )
    _append_probe(
        probes,
        _probe_early_guard_return(source_text, body, body_start, body_end, function),
    )
    _append_probe(
        probes,
        _probe_block_scope(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_loop_init(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_condition_nesting(source_text, body, body_start, body_end, function),
    )
    _append_probe(
        probes,
        _probe_call_arg_temp(source_text, body, body_start, function),
    )
    if operator_filter is not None:
        allowed = frozenset(operator_filter)
        probes = [probe for probe in probes if probe.operator in allowed]
    return probes[:max_probes]


def generate_frame_directed_probes(
    source_text: str,
    function: str,
    *,
    current_frame: dict | None = None,
    target_frame: dict | None = None,
    frame_reservation_delta: int | None = None,
    max_probes: int = 12,
) -> list[LifetimeLayoutProbe]:
    """Generate source variants for frame/local-area residuals.

    These are concrete versions of the levers surfaced by
    `debug suggest frame`: avoid a mutable FP-constant home, split the
    constant lifetime, and move int-to-float scratch lifetimes closer to
    their final use. They are intentionally conservative and only fire for
    one-use local patterns.
    """
    target_size = (
        _frame_size_from_model(target_frame)
        if isinstance(target_frame, dict)
        else None
    )
    current_size = _frame_size_from_model(current_frame or {})
    span = _find_function_body_span(source_text, function)
    if span is None:
        return []
    body_start, body_end = span
    body = source_text[body_start:body_end]
    probes: list[LifetimeLayoutProbe] = []

    if frame_reservation_delta not in (None, 0):
        _append_probe(
            probes,
            _probe_frame_reservation_pad_stack_delta(
                source_text,
                body,
                body_start,
                int(frame_reservation_delta),
            ),
        )
        if len(probes) >= max_probes:
            return probes

    shrink_or_unknown = (
        current_size is None
        or target_size is None
        or current_size > target_size
    )
    if not shrink_or_unknown:
        return probes

    for probe in _probe_frame_local_dematerializations(source_text, function):
        _append_probe(probes, probe)
        if len(probes) >= max_probes:
            return probes
    for probe in _probe_frame_direct_literal_fp_calls(
        source_text,
        body,
        body_start,
        function,
    ):
        _append_probe(probes, probe)
        if len(probes) >= max_probes:
            return probes
    for probe in _probe_frame_split_fp_const_lifetimes(
        source_text,
        body,
        body_start,
        function,
    ):
        _append_probe(probes, probe)
        if len(probes) >= max_probes:
            return probes
    for probe in _probe_frame_magic_scratch_relocations(
        source_text,
        body,
        body_start,
        function,
    ):
        _append_probe(probes, probe)
        if len(probes) >= max_probes:
            return probes
    return probes


def generate_source_lifetime_probes(
    source_text: str,
    function: str,
    *,
    max_probes: int = 12,
) -> tuple[list[LifetimeLayoutProbe], list[dict]]:
    max_probes = max(0, int(max_probes))
    if max_probes == 0:
        return [], []
    targeted_budget = max(1, (max_probes + 1) // 2)
    targeted_generators = (
        ("for-condition-field-reload", _probe_for_condition_field_reload),
        ("repeated-helper-result-reuse", _probe_repeated_helper_result_reuse),
        ("helper-result-dematerialize", _probe_helper_result_dematerialize),
        ("simple-helper-inline-body", _probe_simple_helper_inline_body),
    )
    targeted: list[LifetimeLayoutProbe] = []
    summaries: list[dict] = []
    for operator, generator in targeted_generators:
        candidates, summary = generator(source_text, function)
        summaries.append(summary)
        for probe in candidates:
            if len(targeted) < targeted_budget:
                _append_probe(targeted, probe)
            else:
                summary["retained_candidates"] = targeted_budget
                break
    generic = generate_lifetime_layout_probes(
        source_text,
        function,
        max_probes=max_probes,
        operator_filter=SOURCE_LIFETIME_GENERIC_OPERATORS,
    )
    probes: list[LifetimeLayoutProbe] = []
    for probe in [*targeted, *generic]:
        _append_probe(probes, probe)
        if len(probes) >= max_probes:
            break
    return probes, summaries


@dataclass(frozen=True)
class _SimpleHelperCall:
    callee: str
    args_text: str
    start: int
    end: int
    call_text: str


def _source_lifetime_summary(
    operator: str,
    *,
    status: str,
    candidate_count: int,
    blocker: str | None,
    reason: str,
) -> dict:
    return {
        "operator": operator,
        "status": status,
        "candidate_count": candidate_count,
        "blocker": blocker,
        "reason": reason,
    }


def _probe_for_condition_field_reload(
    source_text: str,
    function: str,
) -> tuple[list[LifetimeLayoutProbe], dict]:
    operator = "for-condition-field-reload"
    span = _find_function_body_span(source_text, function)
    if span is None:
        return [], _source_lifetime_summary(
            operator,
            status="blocked",
            candidate_count=0,
            blocker="function-body-unavailable",
            reason=f"function body for {function} was not found in source",
        )
    body_start, body_end = span
    body = source_text[body_start:body_end]
    code_body = _mask_c_non_code_text(body)
    for match in re.finditer(r"\bfor\s*\(", code_body):
        open_rel = code_body.find("(", match.start())
        if open_rel < 0:
            continue
        open_abs = body_start + open_rel
        close_abs = _find_matching_paren(source_text, open_abs)
        if close_abs is None or close_abs > body_end:
            continue
        header_text = source_text[open_abs + 1:close_abs]
        if _region_has_preprocessor_directive(source_text[body_start + match.start():close_abs]):
            continue
        clauses = _split_top_level_delimited(header_text, ";")
        if len(clauses) != 3 or not all(
            _balanced_expression_delimiters(clause) for clause in clauses
        ):
            continue
        init, condition, increment = clauses
        condition_parts = _split_top_level_delimited(condition, ",")
        if len(condition_parts) != 2:
            continue
        assign_expr, remaining_condition = condition_parts
        assign_match = re.fullmatch(
            r"\s*(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+?)\s*",
            assign_expr,
            re.DOTALL,
        )
        if assign_match is None:
            continue
        reload_name = assign_match.group("name")
        reload_rhs = assign_match.group("rhs").strip()
        if not _for_condition_reload_rhs_is_safe(reload_rhs):
            continue
        if re.search(rf"\b{re.escape(reload_name)}\b", remaining_condition) is None:
            continue
        new_init = _join_nonempty_clauses(init.strip(), f"{reload_name} = {reload_rhs}")
        new_increment = _join_nonempty_clauses(
            increment.strip(),
            f"{reload_name} = {reload_rhs}",
        )
        line_start = _line_start(source_text, body_start + match.start())
        loop_indent = _line_indent_at(source_text, line_start)
        inner_indent = loop_indent + "    "
        replacement = (
            f"{loop_indent}for (\n"
            f"{inner_indent}{new_init};\n"
            f"{inner_indent}{remaining_condition.strip()};\n"
            f"{inner_indent}{new_increment}\n"
            f"{loop_indent})"
        )
        probe = LifetimeLayoutProbe(
            label="for-condition-field-reload-0",
            operator=operator,
            description=(
                "Move a for-condition field reload into init/increment clauses."
            ),
            source_text=(
                source_text[:line_start]
                + replacement
                + source_text[close_abs + 1:]
            ),
            provenance={
                "kind": operator,
                "local": reload_name,
                "reload_rhs": reload_rhs,
            },
        )
        return [probe], _source_lifetime_summary(
            operator,
            status="generated",
            candidate_count=1,
            blocker=None,
            reason="generated safe for-condition field reload candidate",
        )
    return [], _source_lifetime_summary(
        operator,
        status="blocked",
        candidate_count=0,
        blocker="no-for-condition-field-reload",
        reason="source scan found no supported for-condition field reload pattern",
    )


def _probe_repeated_helper_result_reuse(
    source_text: str,
    function: str,
) -> tuple[list[LifetimeLayoutProbe], dict]:
    operator = "repeated-helper-result-reuse"
    span = _find_function_body_span(source_text, function)
    if span is None:
        return [], _source_lifetime_summary(
            operator,
            status="blocked",
            candidate_count=0,
            blocker="function-body-unavailable",
            reason=f"function body for {function} was not found in source",
        )
    body_start, body_end = span
    body = source_text[body_start:body_end]
    calls = _scan_simple_helper_calls(body, absolute_start=body_start)
    groups: dict[str, list[_SimpleHelperCall]] = {}
    for call in calls:
        groups.setdefault(call.call_text, []).append(call)
    first_blocker: tuple[str, str] | None = None
    for occurrences in groups.values():
        if len(occurrences) < 2:
            continue
        first = occurrences[0]
        if not _helper_call_args_are_simple(first.args_text):
            first_blocker = first_blocker or (
                "helper-call-args-unsafe",
                "repeated helper call arguments are not simple enough to rewrite",
            )
            continue
        if not _helper_call_is_read_only(first.callee, source_text, function):
            first_blocker = first_blocker or (
                "callee-not-read-only",
                f"helper `{first.callee}` is not known read-only",
            )
            continue
        line_start = _line_start(source_text, first.start)
        if _line_is_case_or_default_label(source_text, line_start):
            first_blocker = first_blocker or (
                "case-arm-declaration-unsafe",
                "helper result declaration would land directly under a case label",
            )
            continue
        affected_end = _line_end(source_text, occurrences[-1].end)
        if _region_has_preprocessor_directive(source_text[line_start:affected_end]):
            first_blocker = first_blocker or (
                "preprocessor-region-unsafe",
                "helper call region crosses a preprocessor directive",
            )
            continue
        indent = _line_indent_at(source_text, line_start)
        replacements = [(line_start, line_start, (
            f"{indent}s32 ll_probe_helper_result_0 = (s32) {first.call_text};\n"
        ))]
        for call in occurrences:
            replace_start, replace_end = _cast_prefixed_call_range(
                source_text,
                call.start,
                call.end,
            )
            replacements.append((
                replace_start,
                replace_end,
                "ll_probe_helper_result_0",
            ))
        probe = LifetimeLayoutProbe(
            label="repeated-helper-result-reuse-0",
            operator=operator,
            description=(
                f"Materialize repeated helper call `{first.callee}` into one local."
            ),
            source_text=_replace_absolute_slices(source_text, replacements),
            provenance={
                "kind": operator,
                "callee": first.callee,
                "call": first.call_text,
                "occurrences": len(occurrences),
            },
        )
        return [probe], _source_lifetime_summary(
            operator,
            status="generated",
            candidate_count=1,
            blocker=None,
            reason="generated safe repeated helper result reuse candidate",
        )
    blocker, reason = first_blocker or (
        "no-repeated-helper-call",
        "source scan found no supported repeated helper calls",
    )
    return [], _source_lifetime_summary(
        operator,
        status="blocked",
        candidate_count=0,
        blocker=blocker,
        reason=reason,
    )


def _probe_helper_result_dematerialize(
    source_text: str,
    function: str,
) -> tuple[list[LifetimeLayoutProbe], dict]:
    operator = "helper-result-dematerialize"
    span = _find_function_body_span(source_text, function)
    if span is None:
        return [], _source_lifetime_summary(
            operator,
            status="blocked",
            candidate_count=0,
            blocker="function-body-unavailable",
            reason=f"function body for {function} was not found in source",
        )
    body_start, body_end = span
    body = source_text[body_start:body_end]
    first_blocker: tuple[str, str] | None = None
    for match in re.finditer(
        r"(?m)^(?P<indent>[ \t]*)(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expr>[^;\n]+);\s*$",
        body,
    ):
        local = match.group("name")
        expr = match.group("expr").strip()
        call = _standalone_helper_call(expr)
        if call is None:
            continue
        if not _helper_call_args_are_simple(call.args_text):
            first_blocker = first_blocker or (
                "helper-call-args-unsafe",
                "helper result assignment arguments are not simple enough to rewrite",
            )
            continue
        if not _helper_call_is_read_only(call.callee, source_text, function):
            first_blocker = first_blocker or (
                "callee-not-read-only",
                f"helper `{call.callee}` is not known read-only",
            )
            continue
        trailing = body[match.end():]
        use_count = _identifier_count(trailing, local)
        if use_count not in {1, 2}:
            continue
        replacements: list[tuple[int, int, str]] = []
        unsupported = False
        for line_match in re.finditer(r"(?m)^.*\n?", trailing):
            line = line_match.group(0)
            if not line:
                continue
            absolute_start = body_start + match.end() + line_match.start()
            absolute_end = absolute_start + len(line)
            if _region_has_preprocessor_directive(line):
                unsupported = True
                first_blocker = first_blocker or (
                    "preprocessor-region-unsafe",
                    "helper result use crosses a preprocessor directive",
                )
                break
            if _identifier_count(line, local) == 0:
                continue
            rewritten = _rewrite_helper_result_use_line(
                line.rstrip("\n"),
                local,
                call.call_text,
            )
            if rewritten is None:
                unsupported = True
                first_blocker = first_blocker or (
                    "use-statement-unsafe",
                    "helper result use statement is not safe to rewrite",
                )
                break
            suffix = "\n" if line.endswith("\n") else ""
            replacements.append((absolute_start, absolute_end, rewritten + suffix))
        if unsupported or len(replacements) != use_count:
            continue
        assign_start, assign_end = _expand_statement_removal_range(
            source_text,
            body_start + match.start(),
            body_start + match.end(),
        )
        probe = LifetimeLayoutProbe(
            label="helper-result-dematerialize-0",
            operator=operator,
            description=(
                f"Repeat helper call `{call.callee}` at one or two near uses."
            ),
            source_text=_replace_absolute_slices(
                source_text,
                [(assign_start, assign_end, ""), *replacements],
            ),
            provenance={
                "kind": operator,
                "callee": call.callee,
                "local": local,
                "use_count": use_count,
            },
        )
        return [probe], _source_lifetime_summary(
            operator,
            status="generated",
            candidate_count=1,
            blocker=None,
            reason="generated safe helper result dematerialization candidate",
        )
    blocker, reason = first_blocker or (
        "no-helper-result-local",
        "source scan found no supported helper-result local",
    )
    return [], _source_lifetime_summary(
        operator,
        status="blocked",
        candidate_count=0,
        blocker=blocker,
        reason=reason,
    )


def _probe_simple_helper_inline_body(
    source_text: str,
    function: str,
) -> tuple[list[LifetimeLayoutProbe], dict]:
    operator = "simple-helper-inline-body"
    span = _find_function_body_span(source_text, function)
    if span is None:
        return [], _source_lifetime_summary(
            operator,
            status="blocked",
            candidate_count=0,
            blocker="function-body-unavailable",
            reason=f"function body for {function} was not found in source",
        )
    body_start, body_end = span
    calls = _scan_simple_helper_calls(
        source_text[body_start:body_end],
        absolute_start=body_start,
    )
    first_blocker: tuple[str, str] | None = None
    for call in calls:
        if call.callee == function:
            continue
        helper_expr = _simple_helper_expression_body(source_text, call.callee)
        if helper_expr is None:
            if re.search(rf"\b{re.escape(call.callee)}\s*\(", source_text):
                first_blocker = first_blocker or (
                    "helper-body-too-complex",
                    f"helper `{call.callee}` body is not a simple pure expression",
                )
            continue
        if not _helper_call_args_are_simple(call.args_text):
            first_blocker = first_blocker or (
                "helper-call-args-unsafe",
                "helper inline call arguments are not simple enough to substitute",
            )
            continue
        if not _helper_expression_is_pure(helper_expr):
            first_blocker = first_blocker or (
                "helper-body-too-complex",
                f"helper `{call.callee}` body is not a simple pure expression",
            )
            continue
        params = _simple_helper_parameter_names(source_text, call.callee)
        args = tuple(arg.strip() for arg in _split_top_level_args(call.args_text))
        if len(params) != len(args):
            continue
        replacement = helper_expr
        for param, arg in zip(params, args, strict=True):
            replacement = re.sub(rf"\b{re.escape(param)}\b", arg, replacement)
        probe = LifetimeLayoutProbe(
            label="simple-helper-inline-body-0",
            operator=operator,
            description=f"Inline simple same-TU helper `{call.callee}` once.",
            source_text=_replace_absolute_slices(
                source_text,
                [(call.start, call.end, replacement)],
            ),
            provenance={
                "kind": operator,
                "callee": call.callee,
                "parameters": list(params),
            },
        )
        return [probe], _source_lifetime_summary(
            operator,
            status="generated",
            candidate_count=1,
            blocker=None,
            reason="generated simple helper inline-body candidate",
        )
    blocker, reason = first_blocker or (
        "no-simple-helper-inline-body",
        "source scan found no supported same-TU simple helper inline candidate",
    )
    return [], _source_lifetime_summary(
        operator,
        status="blocked",
        candidate_count=0,
        blocker=blocker,
        reason=reason,
    )


def _for_condition_reload_rhs_is_safe(expr: str) -> bool:
    masked = _mask_c_non_code_text(expr).strip()
    if not masked or not _balanced_expression_delimiters(masked):
        return False
    if any(token in masked for token in ("++", "--", "?")):
        return False
    if re.search(r"(?<![=!<>])=(?!=)", masked):
        return False
    return re.fullmatch(
        r"[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)+",
        masked,
    ) is not None


def _helper_call_args_are_simple(args_text: str) -> bool:
    masked = _mask_c_non_code_text(args_text)
    if not _balanced_expression_delimiters(masked):
        return False
    if _region_has_preprocessor_directive(masked):
        return False
    stripped = args_text.strip()
    if not stripped:
        return True
    parts = _split_top_level_args(args_text)
    if not parts:
        parts = (stripped,)
    return all(_helper_expression_fragment_is_simple(part) for part in parts)


def _helper_expression_fragment_is_simple(expr: str) -> bool:
    masked = _mask_c_non_code_text(expr).strip()
    if not masked:
        return False
    if any(token in masked for token in ("++", "--", "?", "#")):
        return False
    if re.search(r"(?<![=!<>])=(?!=)", masked):
        return False
    if "&" in masked:
        return False
    if re.search(r"\b[A-Za-z_]\w*\s*\(", masked):
        return False
    return True


def _helper_expression_is_pure(expr: str) -> bool:
    if not _balanced_expression_delimiters(_mask_c_non_code_text(expr)):
        return False
    if len(_split_top_level_args(expr)) > 1:
        return False
    return _helper_expression_fragment_is_simple(expr)


def _helper_call_is_read_only(callee: str, source: str, function: str) -> bool:
    del function
    if callee in _READ_ONLY_SOURCE_LIFETIME_HELPERS:
        return True
    body_expr = _simple_helper_expression_body(source, callee)
    return body_expr is not None and _helper_expression_is_pure(body_expr)


def _simple_helper_expression_body(source: str, function: str) -> str | None:
    span = _find_function_body_span(source, function)
    if span is None:
        return None
    body_start, body_end = span
    body = source[body_start:body_end]
    if _region_has_preprocessor_directive(body):
        return None
    masked = _mask_c_non_code_text(body)
    match = re.fullmatch(r"\s*return\s+(?P<expr>.+?);\s*", masked, re.DOTALL)
    if match is None:
        return None
    return body[match.start("expr"):match.end("expr")].strip()


def _simple_helper_parameter_names(source: str, function: str) -> tuple[str, ...]:
    span = _find_function_body_span(source, function)
    if span is None:
        return ()
    params = _function_param_text(source, function, span[0])
    if params is None:
        return ()
    names: list[str] = []
    for part in _split_top_level_args(params):
        if part.strip() == "void":
            continue
        parsed = _parse_simple_decl(part)
        if parsed is not None:
            names.append(parsed[0])
    return tuple(names)


def _scan_simple_helper_calls(
    text: str,
    *,
    absolute_start: int = 0,
) -> list[_SimpleHelperCall]:
    calls: list[_SimpleHelperCall] = []
    masked = _mask_c_non_code_text(text)
    cursor = 0
    keywords = {"if", "for", "while", "switch", "return", "sizeof"}
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
    while cursor < len(masked):
        match = pattern.search(masked, cursor)
        if match is None:
            break
        start = match.start()
        callee = match.group(1)
        open_index = masked.find("(", start, match.end())
        if open_index < 0:
            break
        if callee in keywords:
            cursor = open_index + 1
            continue
        close_index = _find_matching_paren(masked, open_index)
        if close_index is None:
            break
        calls.append(_SimpleHelperCall(
            callee=callee,
            args_text=text[open_index + 1:close_index],
            start=absolute_start + start,
            end=absolute_start + close_index + 1,
            call_text=text[start:close_index + 1],
        ))
        cursor = close_index + 1
    return calls


def _standalone_helper_call(expr: str) -> _SimpleHelperCall | None:
    stripped = expr.strip()
    cast_match = re.match(r"^\(\s*[A-Za-z_]\w*\s*\)\s*", stripped)
    if cast_match is not None:
        stripped = stripped[cast_match.end():]
    calls = _scan_simple_helper_calls(stripped)
    if len(calls) != 1:
        return None
    call = calls[0]
    if call.start != 0 or call.end != len(stripped):
        return None
    return call


def _rewrite_helper_result_use_line(
    line: str,
    name: str,
    replacement: str,
) -> str | None:
    if _identifier_count(line, name) != 1:
        return None
    return_match = re.match(
        rf"^(?P<prefix>\s*return\s+){re.escape(name)}(?P<suffix>\s*;\s*)$",
        line,
    )
    if return_match is not None:
        return (
            f"{return_match.group('prefix')}{replacement}"
            f"{return_match.group('suffix')}"
        )
    assign_match = _SIMPLE_RHS_ASSIGN_USE_RE.match(line)
    if assign_match is not None and assign_match.group("rhs") == name:
        return (
            f"{assign_match.group('indent')}{assign_match.group('lhs')} = "
            f"{replacement};"
        )
    call_match = re.match(
        r"^(?P<indent>\s*)(?P<callee>[A-Za-z_]\w*)\((?P<args>[^;\n]*)\);\s*$",
        line,
    )
    if call_match is None:
        return None
    args = list(_split_top_level_args(call_match.group("args")))
    matches = [idx for idx, arg in enumerate(args) if arg.strip() == name]
    if len(matches) != 1:
        return None
    for idx, arg in enumerate(args):
        if idx == matches[0]:
            continue
        if not _helper_expression_fragment_is_simple(arg):
            return None
    args[matches[0]] = replacement
    return (
        f"{call_match.group('indent')}{call_match.group('callee')}"
        f"({', '.join(args)});"
    )


def _split_top_level_delimited(text: str, delimiter: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for idx, char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
        elif char in closing:
            if not stack or stack.pop() != char:
                return ()
        elif char == delimiter and not stack:
            parts.append(text[start:idx])
            start = idx + 1
    if stack:
        return ()
    parts.append(text[start:])
    return tuple(parts)


def _join_nonempty_clauses(left: str, right: str) -> str:
    if left and right:
        return f"{left}, {right}"
    return left or right


def _line_start(source: str, offset: int) -> int:
    return source.rfind("\n", 0, offset) + 1


def _line_end(source: str, offset: int) -> int:
    end = source.find("\n", offset)
    if end < 0:
        return len(source)
    return end + 1


def _line_indent_at(source: str, line_start: int) -> str:
    match = re.match(r"[ \t]*", source[line_start:])
    return "" if match is None else match.group(0)


def _line_is_case_or_default_label(source: str, line_start: int) -> bool:
    line_end = source.find("\n", line_start)
    if line_end < 0:
        line_end = len(source)
    stripped = source[line_start:line_end].strip()
    return stripped.startswith("case ") or stripped == "default:"


def _cast_prefixed_call_range(
    source: str,
    call_start: int,
    call_end: int,
) -> tuple[int, int]:
    line_start = _line_start(source, call_start)
    prefix = source[line_start:call_start]
    match = re.search(r"\(\s*s32\s*\)\s*$", prefix)
    if match is None:
        return call_start, call_end
    return line_start + match.start(), call_end


def _frame_size_from_model(model: dict) -> int | None:
    try:
        raw = model.get("frame_size")
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


_FLOAT_LITERAL_RE = (
    r"[-+]?(?:(?:\d+\.\d*)|(?:\d*\.\d+)|(?:\d+))(?:[fF])?"
)


@dataclass(frozen=True)
class _FpConstCandidate:
    name: str
    literal: str
    decl_start: int
    decl_end: int
    decl_indent: str
    decl_replacement: str | None
    assign_start: int | None
    assign_end: int | None
    assign_text: str
    call_start: int
    call_end: int
    call_replacement: str
    call_name: str


def _probe_frame_direct_literal_fp_calls(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for cand in _fp_const_candidates(body):
        replacements = [
            (cand.decl_start, cand.decl_end, ""),
            (cand.call_start, cand.call_end, cand.call_replacement),
        ]
        if cand.assign_start is not None and cand.assign_end is not None:
            replacements.append((cand.assign_start, cand.assign_end, ""))
        mutated = _replace_body_slices(source, body_start, replacements)
        probes.append(LifetimeLayoutProbe(
            label=f"frame-direct-literal-at-final-fp-call-{cand.name}",
            operator="frame-direct-literal-at-final-fp-call",
            description=(
                f"Pass `{cand.literal}` directly to {cand.call_name} instead "
                f"of keeping one-use FP local `{cand.name}`."
            ),
            source_text=mutated,
            provenance={
                "kind": "frame-direct-literal-at-final-fp-call",
                "variable": cand.name,
                "literal": cand.literal,
                "call": cand.call_name,
            },
        ))
    return probes


def _probe_frame_split_fp_const_lifetimes(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    for cand in _fp_const_candidates(body):
        insert = f"{cand.decl_indent}{cand.assign_text.strip()}\n"
        replacements: list[tuple[int, int, str]] = [
            (cand.call_start, cand.call_start, insert),
        ]
        if cand.assign_start is not None and cand.assign_end is not None:
            replacements.append((cand.assign_start, cand.assign_end, ""))
        elif cand.decl_replacement is not None:
            replacements.append(
                (cand.decl_start, cand.decl_end, cand.decl_replacement)
            )
        mutated = _replace_body_slices(source, body_start, replacements)
        if mutated == source:
            continue
        probes.append(LifetimeLayoutProbe(
            label=f"frame-split-fp-const-lifetime-{cand.name}",
            operator="frame-split-fp-const-lifetime",
            description=(
                f"Move one-use FP constant `{cand.name}` assignment next to "
                f"its {cand.call_name} use."
            ),
            source_text=mutated,
            provenance={
                "kind": "frame-split-fp-const-lifetime",
                "variable": cand.name,
                "literal": cand.literal,
                "call": cand.call_name,
            },
        ))
    return probes


def _probe_frame_magic_scratch_relocations(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    assign_re = re.compile(
        r"(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*\(f32\)\s*([^;\n]+);[ \t]*\n?"
    )
    for assign in assign_re.finditer(body):
        indent, name, expr = assign.groups()
        if not _has_simple_f32_declaration(body, name, before=assign.start()):
            continue
        if len(re.findall(rf"\b{re.escape(name)}\b", body)) != 3:
            continue
        call = _find_later_call_using_name(body, assign.end(), name)
        if call is None:
            continue
        if not _call_has_top_level_arg(call.group("args"), name):
            continue
        between = body[assign.end():call.start()]
        if re.search(rf"\b{re.escape(name)}\b", between):
            continue
        insert = f"{indent}{name} = (f32) {expr.strip()};\n"
        if body[assign.end():call.start()].strip() == "":
            continue
        mutated = _replace_body_slices(
            source,
            body_start,
            [
                (call.start(), call.start(), insert),
                (assign.start(), assign.end(), ""),
            ],
        )
        probes.append(LifetimeLayoutProbe(
            label=f"frame-magic-scratch-relocation-{name}",
            operator="frame-magic-scratch-relocation",
            description=(
                f"Move int-to-float scratch assignment for `{name}` next to "
                f"its final call use."
            ),
            source_text=mutated,
            provenance={
                "kind": "frame-magic-scratch-relocation",
                "variable": name,
            },
        ))
    return probes


def _fp_const_candidates(body: str) -> list[_FpConstCandidate]:
    candidates: list[_FpConstCandidate] = []
    decl_re = re.compile(
        rf"(?m)^([ \t]*)f32\s+([A-Za-z_]\w*)\s*(?:=\s*({_FLOAT_LITERAL_RE}))?;[ \t]*\n?"
    )
    for decl in decl_re.finditer(body):
        indent, name, init_literal = decl.groups()
        literal = init_literal
        assign_start: int | None = None
        assign_end: int | None = None
        assign_text: str
        if literal is None:
            assign_re = re.compile(
                rf"(?m)^([ \t]*){re.escape(name)}\s*=\s*({_FLOAT_LITERAL_RE});[ \t]*\n?"
            )
            assign = assign_re.search(body, decl.end())
            if assign is None:
                continue
            literal = assign.group(2)
            assign_start = assign.start()
            assign_end = assign.end()
            assign_text = assign.group(0)
            expected_uses = 3
            search_start = assign.end()
            decl_replacement = None
        else:
            assign_text = f"{indent}{name} = {literal};\n"
            expected_uses = 2
            search_start = decl.end()
            decl_replacement = f"{indent}f32 {name};\n"
        if len(re.findall(rf"\b{re.escape(name)}\b", body)) != expected_uses:
            continue
        call = _find_later_call_using_name(body, search_start, name)
        if call is None:
            continue
        args = list(_split_top_level_args(call.group("args")))
        replaced = False
        for idx, arg in enumerate(args):
            if arg.strip() == name:
                args[idx] = literal
                replaced = True
                break
        if not replaced:
            continue
        call_replacement = (
            f"{call.group('indent')}{call.group('callee')}"
            f"({', '.join(args)});{call.group('newline')}"
        )
        candidates.append(_FpConstCandidate(
            name=name,
            literal=literal,
            decl_start=decl.start(),
            decl_end=decl.end(),
            decl_indent=indent,
            decl_replacement=decl_replacement,
            assign_start=assign_start,
            assign_end=assign_end,
            assign_text=assign_text,
            call_start=call.start(),
            call_end=call.end(),
            call_replacement=call_replacement,
            call_name=call.group("callee"),
        ))
    return candidates


def _find_later_call_using_name(
    body: str,
    start: int,
    name: str,
) -> re.Match[str] | None:
    call_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)(?P<callee>[A-Za-z_]\w*)"
        r"\((?P<args>[^;\n]*)\);[ \t]*(?P<newline>\n?)"
    )
    for call in call_re.finditer(body, start):
        if re.search(rf"\b{re.escape(name)}\b", call.group("args")):
            return call
    return None


def _call_has_top_level_arg(args_text: str, name: str) -> bool:
    return any(arg.strip() == name for arg in _split_top_level_args(args_text))


def _has_simple_f32_declaration(body: str, name: str, *, before: int) -> bool:
    prefix = body[:before]
    return re.search(
        rf"(?m)^[ \t]*f32\s+{re.escape(name)}\s*(?:;|=)",
        prefix,
    ) is not None


def _replace_body_slices(
    source: str,
    body_start: int,
    replacements: list[tuple[int, int, str]],
) -> str:
    mutated = source
    for rel_start, rel_end, replacement in sorted(
        replacements,
        key=lambda item: (item[0], item[1]),
        reverse=True,
    ):
        start = body_start + rel_start
        end = body_start + rel_end
        mutated = mutated[:start] + replacement + mutated[end:]
    return mutated


def _replace_absolute_slices(
    source: str,
    replacements: list[tuple[int, int, str]],
) -> str:
    mutated = source
    for start, end, replacement in sorted(
        replacements,
        key=lambda item: (item[0], item[1]),
        reverse=True,
    ):
        mutated = mutated[:start] + replacement + mutated[end:]
    return mutated


def _expand_statement_removal_range(
    source: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    if end < len(source) and source[end] == "\n":
        end += 1
    return start, end


def _identifier_count(text: str, name: str) -> int:
    return len(re.findall(r"\b" + re.escape(name) + r"\b", text))


def _identifier_count_excluding_ranges(
    source: str,
    name: str,
    excluded_ranges: list[tuple[int, int]],
) -> int:
    chars = list(source)
    for start, end in excluded_ranges:
        for idx in range(max(0, start), min(len(chars), end)):
            chars[idx] = " "
    return _identifier_count("".join(chars), name)


def _byte_to_char_offsets(source: str) -> list[int]:
    mapping = [0] * (len(source.encode("utf-8")) + 1)
    byte_offset = 0
    for char_index, char in enumerate(source):
        encoded_len = len(char.encode("utf-8"))
        for rel in range(encoded_len):
            mapping[byte_offset + rel] = char_index
        byte_offset += encoded_len
        mapping[byte_offset] = char_index + 1
    return mapping


def _span_char_range(
    source: str,
    span: StatementSpan,
    byte_to_char: list[int] | None = None,
) -> tuple[int, int]:
    mapping = byte_to_char if byte_to_char is not None else _byte_to_char_offsets(source)
    start, end = span.byte_range
    if start >= len(mapping) or end >= len(mapping):
        return len(source), len(source)
    return mapping[start], mapping[end]


def _span_source(
    source: str,
    span: StatementSpan,
    byte_to_char: list[int] | None = None,
) -> str:
    start, end = _span_char_range(source, span, byte_to_char)
    return source[start:end]


def _is_simple_dematerialize_type(type_text: str) -> bool:
    stripped = type_text.strip()
    compact = " ".join(stripped.replace("*", " * ").split())
    if any(
        token in compact.split()
        for token in {"volatile", "static", "register", "extern", "auto"}
    ):
        return False
    if compact.startswith(("struct ", "union ", "enum ")):
        return False
    if re.fullmatch(
        r"(?:const\s+)?[A-Za-z_]\w*(?:\s*\*)*",
        stripped,
    ) is None:
        return False
    if "*" in stripped:
        return True
    scalar_name = stripped.removeprefix("const ").strip()
    return scalar_name in _DEMATERIALIZE_SCALAR_TYPES


def _safe_dematerialize_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr or not _balanced_expression_delimiters(expr):
        return False
    if any(token in expr for token in ("++", "--", "?", ",")):
        return False
    if re.search(r"(?<![=!<>])=(?!=)", expr):
        return False
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return False
    if "&" in expr or "->" in expr:
        return False
    return True


def _has_preprocessor_between(source: str, start: int, end: int) -> bool:
    return re.search(r"(?m)^[ \t]*#", source[start:end]) is not None


def _is_inert_intervening_declaration(
    source: str,
    span: StatementSpan,
    byte_to_char: list[int],
) -> bool:
    return _SIMPLE_LOCAL_BARE_DECL_RE.match(
        _span_source(source, span, byte_to_char)
    ) is not None


def _span_mentions_identifier(
    source: str,
    span: StatementSpan,
    name: str,
    byte_to_char: list[int] | None = None,
) -> bool:
    return _identifier_count(_span_source(source, span, byte_to_char), name) > 0


def _split_top_level_args_with_ranges(
    args_text: str,
    *,
    absolute_start: int,
) -> tuple[tuple[str, int, int], ...]:
    args: list[tuple[str, int, int]] = []
    start = 0
    depth = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for idx, char in enumerate(args_text):
        if char in pairs:
            depth += 1
        elif char in closing and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            raw = args_text[start:idx]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            args.append((
                raw.strip(),
                absolute_start + start + leading,
                absolute_start + start + trailing,
            ))
            start = idx + 1
    raw = args_text[start:]
    if raw.strip():
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        args.append((
            raw.strip(),
            absolute_start + start + leading,
            absolute_start + start + trailing,
        ))
    return tuple(args)


def _target_pair_states(
    pcdump_text: str,
    function: str,
    pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...],
) -> tuple[TargetPairState, ...]:
    if not pairs:
        return ()
    report = explain_virtuals(
        pcdump_text,
        function,
        virtuals=[],
        pairs=pairs,
    )
    return tuple(
        TargetPairState(
            virtual=pair.virtual,
            other_virtual=pair.other_virtual,
            colorgraph_interference=pair.colorgraph_interference,
            live_overlap=pair.live_overlap,
            same_assigned_reg=pair.same_assigned_reg,
            reason=pair.reason,
        )
        for pair in report.pair_interferences
    )


def _frame_and_saved_regs(fn: Function | None) -> tuple[int | None, tuple[str, ...]]:
    if fn is None:
        return None, ()
    selected = _select_final_pass(fn)
    if selected is None:
        return None, ()
    frame_size: int | None = None
    saved: set[str] = set()
    instructions = [
        instr
        for block in selected.blocks[:2]
        for instr in block.instructions[:32]
    ]
    for instr in instructions:
        if instr.opcode == "stwu" and frame_size is None:
            match = _FRAME_RE.search(instr.operands)
            if match is not None:
                frame_size = abs(int(match.group(1), 0))
        if instr.opcode == "stmw":
            match = _STMW_RE.search(instr.operands)
            if match is not None:
                start = int(match.group(1))
                if 13 <= start <= 31:
                    saved.update(f"r{reg}" for reg in range(start, 32))
        elif instr.opcode == "stw":
            match = _STW_RE.search(instr.operands)
            if match is not None:
                reg = int(match.group(1))
                if 13 <= reg <= 31:
                    saved.add(f"r{reg}")
        elif instr.opcode == "stfd":
            match = _STFD_RE.search(instr.operands)
            if match is not None:
                reg = int(match.group(1))
                if 14 <= reg <= 31:
                    saved.add(f"f{reg}")
    return frame_size, tuple(sorted(saved, key=_reg_sort_key))


def _select_final_pass(fn: Function) -> Pass | None:
    preferred = (
        "FINAL CODE AFTER INSTRUCTION SCHEDULING",
        "AFTER PEEPHOLE OPTIMIZATION",
        "AFTER MERGING EPILOGUE, PROLOGUE",
        "AFTER GENERATING EPILOGUE, PROLOGUE",
    )
    by_name = {p.name: p for p in fn.passes}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return fn.passes[-1] if fn.passes else None


def _reg_sort_key(reg: str) -> tuple[int, int]:
    return (0 if reg.startswith("r") else 1, int(reg[1:]))


def _fmt_regs(regs: tuple[str, ...]) -> str:
    return ",".join(regs) if regs else "-"


def _fmt_ints(values: tuple[int, ...]) -> str:
    return ",".join(str(v) for v in values) if values else "-"


def _append_probe(
    probes: list[LifetimeLayoutProbe],
    probe: LifetimeLayoutProbe | None,
) -> None:
    if probe is None:
        return
    if probe.source_text in {existing.source_text for existing in probes}:
        return
    probes.append(probe)


def _find_function_body_span(source: str, function: str) -> tuple[int, int] | None:
    for match in re.finditer(rf"\b{re.escape(function)}\s*\(", source):
        open_paren = source.find("(", match.start(), match.end())
        if open_paren < 0:
            continue
        close_paren = _find_matching_paren(source, open_paren)
        if close_paren is None:
            continue
        cursor = close_paren + 1
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        if cursor >= len(source) or source[cursor] != "{":
            continue
        depth = 0
        for idx in range(cursor, len(source)):
            char = source[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return cursor + 1, idx
    return None


def _replace_body_slice(
    source: str,
    body_start: int,
    rel_start: int,
    rel_end: int,
    replacement: str,
) -> str:
    start = body_start + rel_start
    end = body_start + rel_end
    return source[:start] + replacement + source[end:]


def _probe_temp_introduction(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*([^;\n]*(?:\+|-|\*|/)[^;\n]*);",
        body,
    )
    declaration = False
    if match is None:
        match = re.search(
            r"(?m)^([ \t]*)((?:s32|u32|int|float|double)\s+"
            r"([A-Za-z_]\w*))\s*=\s*([^;\n]*(?:\+|-|\*|/)[^;\n]*);",
            body,
        )
        if match is None:
            return None
        declaration = True
    temp = "ll_probe_temp_0"
    if declaration:
        indent, decl_lhs, lhs, expr = match.groups()
        if _has_later_decl_before_statement(body, match.end(), indent):
            return None
        replacement = (
            f"{indent}{decl_lhs};\n"
            f"{indent}int {temp} = {expr.strip()};\n"
            f"{indent}{lhs} = {temp};"
        )
    else:
        indent, lhs, expr = match.groups()
        replacement = (
            f"{indent}int {temp} = {expr.strip()};\n"
            f"{indent}{lhs} = {temp};"
        )
    return LifetimeLayoutProbe(
        label="temp-introduction-0",
        operator="temp-introduction",
        description="Introduce a named temp for one compound assignment RHS.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), match.end(), replacement
        ),
    )


def _has_later_decl_before_statement(body: str, start: int, indent: str) -> bool:
    for line in body[start:].splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith(indent):
            return False
        if _LOCAL_DECL_RE.match(line):
            return True
        return False
    return False


def _probe_temp_removal(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)(?:s32|u32|int|float|double|[A-Za-z_]\w+\s*\*)\s+"
        r"([A-Za-z_]\w*)\s*=\s*([^;\n]+);\n"
        r"((?:[ \t]*(?:s32|u32|int|float|double|[A-Za-z_]\w+\s*\*)\s+"
        r"[A-Za-z_]\w*(?:\s*=\s*[^;\n]+)?;\n){0,2})"
        r"([ \t]*)([A-Za-z_]\w*)\s*=\s*\2\s*;",
        body,
    )
    if match is None:
        return None
    _indent, temp, expr, middle, assign_indent, lhs = match.groups()
    replacement = f"{middle}{assign_indent}{lhs} = {expr.strip()};"
    return LifetimeLayoutProbe(
        label="temp-removal-0",
        operator="temp-removal",
        description=f"Inline one-use temp `{temp}` into the following assignment.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), match.end(), replacement
        ),
    )


def _probe_type_width(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    replacements = {
        "s32": "int",
        "int": "s32",
        "u8": "u32",
        "s8": "s32",
        "u16": "u32",
        "s16": "s32",
        "u32": "u16",
    }
    match = re.search(
        r"(?m)^([ \t]*)(s32|u32|int|u16|s16|u8|s8)\s+([A-Za-z_]\w*)\s*(?=[=;])",
        body,
    )
    if match is None:
        return None
    old_type = match.group(2)
    new_type = replacements[old_type]
    replacement = f"{match.group(1)}{new_type} {match.group(3)}"
    return LifetimeLayoutProbe(
        label="type-width-0",
        operator="type-width",
        description=f"Change local `{match.group(3)}` type {old_type} -> {new_type}.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), match.end(), replacement
        ),
    )


def _probe_declaration_use_distance(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    for match in re.finditer(
        r"(?m)^([ \t]*)(?:int|s32|u32|float|double|[A-Za-z_]\w+\s*\*)\s+"
        r"([A-Za-z_]\w*)\s*;\n",
        body,
    ):
        indent, name = match.groups()
        use_start = _first_later_line_with_identifier(body, match.end(), name)
        if use_start is None:
            continue
        use_line_end = body.find("\n", use_start)
        if use_line_end < 0:
            use_line_end = len(body)
        use_line = body[use_start:use_line_end]
        if re.match(rf"\s*for\s*\(\s*{re.escape(name)}\s*=", use_line):
            continue
        between = body[match.end():use_start]
        if not between.strip():
            continue
        paragraph = body[use_start:_paragraph_end(body, use_start)]
        if _block_crosses_shallower_else(paragraph, use_line):
            continue
        use_end = _declaration_use_region_end(body, use_start, name)
        if use_end is None:
            continue
        use_block = body[use_start:use_end]
        if _block_crosses_shallower_else(use_block, use_line):
            continue
        decl_text = match.group(0).strip()
        wrapped = (
            f"{indent}{{\n"
            f"{indent}    {decl_text}\n"
            f"{_indent_block_lines(use_block, indent)}"
            f"{indent}}}\n"
        )
        moved_body = body[:match.start()] + body[match.end():use_start]
        moved_body += wrapped
        moved_body += body[use_end:]
        return LifetimeLayoutProbe(
            label="declaration-use-distance-0",
            operator="declaration-use-distance",
            description=f"Move `{name}` declaration down next to its first use.",
            source_text=(
                source[:body_start] + moved_body + source[body_start + len(body):]
            ),
        )
    return None


def _probe_early_guard_return(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    if re.search(rf"\bvoid\s+{re.escape(function)}\s*\(", source[:body_start]) is None:
        return None
    for match in re.finditer(r"(?m)^([ \t]*)if\s*\(", body):
        indent = match.group(1)
        condition_start = body_start + match.end() - 1
        condition_end = _find_matching_paren(source, condition_start)
        if condition_end is None or condition_end > body_end:
            continue
        open_brace = source.find("{", condition_end, body_end)
        if open_brace < 0:
            continue
        close_brace = _find_matching_brace(source, open_brace)
        if close_brace is None or close_brace > body_end:
            continue
        trailing = source[close_brace + 1:body_end].lstrip()
        if trailing.startswith("else"):
            continue
        condition = source[condition_start + 1:condition_end].strip()
        inner = source[open_brace + 1:close_brace]
        unwrapped = _outdent_block_lines(inner, indent + "    ", indent)
        if unwrapped.startswith("\n"):
            unwrapped = unwrapped[1:]
        replacement = (
            f"{indent}if (!({condition})) {{\n"
            f"{indent}    return;\n"
            f"{indent}}}\n"
            f"{unwrapped}"
        )
        return LifetimeLayoutProbe(
            label="early-guard-return-0",
            operator="early-guard-return",
            description="Invert a top-level guard and unwrap its body after return.",
            source_text=source[:body_start + match.start()]
            + replacement
            + source[close_brace + 1:],
        )
    return None


def _probe_block_scope(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|s32|u32|int|float|double|[A-Za-z_]\w*)"
        r"(?:\s*\*)*\s+[A-Za-z_]\w*(?:\s*=\s*[^;\n]+)?;\n",
        body,
    )
    if match is None:
        return None
    indent = match.group(1)
    names = _leading_local_decl_names(body[match.start():])
    if not names:
        return None
    block_end = _last_line_end_for_identifiers(body, match.start(), names)
    if block_end is None:
        return None
    block_end = max(block_end, match.end())
    block_end = _balanced_region_end(body, match.start(), block_end)
    block_text = body[match.start():block_end]
    first_line_end = body.find("\n", match.start())
    if first_line_end < 0:
        first_line_end = match.end()
    first_line = body[match.start():first_line_end]
    if _block_crosses_shallower_else(block_text, first_line):
        return None
    replacement = _wrap_block_text(block_text, indent)
    return LifetimeLayoutProbe(
        label="block-scope-0",
        operator="block-scope",
        description="Tighten one local declaration and following statement into a block.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), block_end, replacement
        ),
    )


def _probe_loop_init(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    decl = re.search(r"(?m)^([ \t]*)(int|s32)\s+([A-Za-z_]\w*)\s*;\n", body)
    if decl is None:
        return None
    indent, typ, var = decl.groups()
    for_match = re.search(
        rf"(?m)^([ \t]*)for\s*\(\s*{re.escape(var)}\s*=",
        body[decl.end():],
    )
    if for_match is None:
        return None
    rel_for_start = decl.end() + for_match.start()
    between = body[decl.end():rel_for_start]
    if re.search(rf"\b{re.escape(var)}\b", between):
        return None
    abs_for_start = body_start + rel_for_start
    abs_for_open = source.find("{", abs_for_start, body_start + len(body))
    if abs_for_open < 0:
        return None
    abs_for_close = _find_matching_brace(source, abs_for_open)
    if abs_for_close is None or abs_for_close > body_start + len(body):
        return None

    decl_abs_start = body_start + decl.start()
    decl_abs_end = body_start + decl.end()
    loop_indent = for_match.group(1)
    loop_text = source[abs_for_start:abs_for_close + 1]
    indented_loop = _indent_block_lines(loop_text, loop_indent)
    if not indented_loop.endswith("\n"):
        indented_loop += "\n"
    replacement = (
        f"{loop_indent}{{\n"
        f"{loop_indent}    {typ} {var};\n"
        f"{indented_loop}"
        f"{loop_indent}}}"
    )
    mutated = (
        source[:decl_abs_start]
        + source[decl_abs_end:abs_for_start]
        + replacement
        + source[abs_for_close + 1:]
    )
    return LifetimeLayoutProbe(
        label="loop-init-0",
        operator="loop-init",
        description=f"Move `{var}` declaration into a tight block around the loop.",
        source_text=mutated,
    )


def _probe_condition_nesting(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)if\s*\(([^()\n]+)\s*&&\s*([^()\n]+)\)\s*\{",
        body,
    )
    if match is None:
        return None
    absolute_open = body_start + match.end() - 1
    absolute_close = _find_matching_brace(source, absolute_open)
    if absolute_close is None or absolute_close > body_end:
        return None
    if source[absolute_close + 1:body_end].lstrip().startswith("else"):
        return None
    indent, left, right = match.groups()
    header = f"{indent}if ({left.strip()}) {{\n{indent}    if ({right.strip()}) {{"
    start = body_start + match.start()
    end = body_start + match.end()
    mutated = source[:start] + header + source[end:absolute_close + 1]
    mutated += f"\n{indent}}}" + source[absolute_close + 1:]
    return LifetimeLayoutProbe(
        label="condition-nesting-0",
        operator="condition-nesting",
        description="Split a conjunctive condition into nested if statements.",
        source_text=mutated,
    )


def _probe_call_arg_temp(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    scoped_types = _scoped_identifier_types(source, body, body_start, function)
    for match in re.finditer(
        r"(?m)^([ \t]*)([A-Za-z_]\w*)\(([^;\n]*)\);",
        body,
    ):
        indent, call, args_text = match.groups()
        if not _balanced_expression_delimiters(args_text):
            continue
        args = list(_split_top_level_args(args_text))
        for index, arg in enumerate(args):
            if not _has_tempizable_arithmetic(arg):
                continue
            temp = "ll_probe_arg_0"
            temp_type = _infer_call_arg_temp_type(arg, scoped_types)
            args[index] = temp
            replacement = (
                f"{indent}{{\n"
                f"{indent}    {temp_type} {temp} = {arg.strip()};\n"
                f"{indent}    {call}({', '.join(args)});\n"
                f"{indent}}}"
            )
            return LifetimeLayoutProbe(
                label="call-arg-tempization-0",
                operator="call-argument-tempization",
                description="Hoist one compound call argument into a named temp.",
                source_text=_replace_body_slice(
                    source, body_start, match.start(), match.end(), replacement
                ),
                provenance={
                    "kind": "call-argument-tempization",
                    "call": call,
                    "argument_index": index,
                    "temp_type": temp_type,
                },
            )
    return None


def scan_frame_local_dematerialization_probes(
    source: str,
    function: str,
) -> tuple[list[LifetimeLayoutProbe], dict]:
    operator = "frame-local-dematerialize"
    body_span = _find_function_body_span(source, function)
    if body_span is None:
        return [], {
            "status": "scan-unavailable",
            "operator": operator,
            "reason": f"function body for {function} was not found in source",
        }
    try:
        spans = list_statement_spans(source, function)
    except Exception as exc:
        return [], {
            "status": "scan-error",
            "operator": operator,
            "reason": f"source span scan failed: {exc}",
        }
    probes = _probe_frame_local_dematerializations_from_spans(
        source,
        function,
        spans,
        body_span,
    )
    if probes:
        return probes, {
            "status": "semantic-lever-generated",
            "operator": operator,
            "candidate_count": len(probes),
    }
    blockers = _frame_local_dematerialization_blockers(
        source,
        spans,
    )
    reason = "source scan found no safe semantic local dematerialization"
    if blockers:
        labels = ", ".join(_frame_local_blocker_label(item) for item in blockers)
        reason = f"{reason}; blockers: {labels}"
        return [], {
            "status": "no-safe-semantic-lever",
            "operator": operator,
            "reason": reason,
            "blockers": blockers,
        }
    return [], {
        "status": "no-safe-semantic-lever",
        "operator": operator,
        "reason": reason,
    }


def _probe_frame_local_dematerializations(
    source: str,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes, _status = scan_frame_local_dematerialization_probes(source, function)
    return probes


def _probe_frame_local_dematerializations_from_spans(
    source: str,
    function: str,
    spans: list[StatementSpan],
    body_span: tuple[int, int],
) -> list[LifetimeLayoutProbe]:
    if not spans:
        return []
    byte_to_char = _byte_to_char_offsets(source)
    probes: list[LifetimeLayoutProbe] = []
    for idx, span in enumerate(spans):
        candidate = _frame_local_initialized_candidate(source, spans, idx, byte_to_char)
        if candidate is None:
            candidate = _frame_local_assigned_candidate(source, spans, idx, byte_to_char)
        if candidate is None:
            continue
        (
            name,
            type_text,
            expr,
            action,
            definition_spans,
            value_span,
            next_search_index,
        ) = candidate
        use_idx = _find_frame_local_use_index(
            source,
            spans,
            next_search_index,
            value_span,
            name,
            byte_to_char,
        )
        if use_idx is None:
            continue
        use_span = spans[use_idx]
        rewrite = _rewrite_frame_local_use(
            source,
            use_span,
            name=name,
            type_text=type_text,
            expr=expr,
            byte_to_char=byte_to_char,
        )
        if rewrite is None:
            continue
        replacement_start, replacement_end, replacement, use_kind = rewrite
        removal_ranges = [
            _expand_statement_removal_range(
                source,
                *_span_char_range(source, def_span, byte_to_char),
            )
            for def_span in definition_spans
        ]
        use_start, use_end = _span_char_range(source, use_span, byte_to_char)
        if not _frame_local_only_definition_and_use(
            source,
            body_span=body_span,
            name=name,
            definition_ranges=removal_ranges,
            use_range=(use_start, use_end),
        ):
            continue
        replacements = [(replacement_start, replacement_end, replacement)]
        replacements.extend((start, end, "") for start, end in removal_ranges)
        probes.append(LifetimeLayoutProbe(
            label=f"frame-local-dematerialize-{name}",
            operator="frame-local-dematerialize",
            description=f"Inline one-use local `{name}` into its use.",
            source_text=_replace_absolute_slices(source, replacements),
            provenance={
                "kind": "frame-local-dematerialize",
                "local": name,
                "action": action,
                "expression": expr,
                "cast_type": type_text,
                "use_kind": use_kind,
                "definition_lines": [
                    definition_spans[0].line_range[0],
                    definition_spans[-1].line_range[1],
                ],
                "use_lines": [use_span.line_range[0], use_span.line_range[1]],
            },
        ))
    return probes


def _frame_local_dematerialization_blockers(
    source: str,
    spans: list[StatementSpan],
) -> list[dict]:
    byte_to_char = _byte_to_char_offsets(source)
    blockers: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for idx, span in enumerate(spans):
        initialized = _frame_local_initialized_candidate(
            source,
            spans,
            idx,
            byte_to_char,
        )
        if initialized is not None:
            (
                name,
                type_text,
                _expr,
                _action,
                definition_spans,
                value_span,
                next_search_index,
            ) = initialized
            use_spans = _later_identifier_spans(
                source,
                spans,
                next_search_index,
                value_span,
                name,
                byte_to_char,
            )
            use_count = sum(
                _identifier_count(_span_source(source, use, byte_to_char), name)
                for use in use_spans
            )
            key = ("multi-use-local", name)
            if use_count > 1 and key not in seen:
                seen.add(key)
                blockers.append({
                    "kind": "multi-use-local",
                    "local": name,
                    "type": type_text,
                    "definition_lines": [
                        definition_spans[0].line_range[0],
                        definition_spans[-1].line_range[1],
                    ],
                    "use_count": use_count,
                    "use_lines": [
                        [use.line_range[0], use.line_range[1]]
                        for use in use_spans
                    ],
                })
            continue

        decl_match = _SIMPLE_LOCAL_BARE_DECL_RE.match(
            _span_source(source, span, byte_to_char)
        )
        if decl_match is None:
            continue
        name = decl_match.group("name")
        type_text = " ".join(decl_match.group("type").split())
        if _is_simple_dematerialize_type(type_text):
            continue
        later_spans = _later_same_scope_spans(spans, idx + 1, span)
        address_uses = [
            later
            for later in later_spans
            if _span_has_address_taken_identifier(
                source,
                later,
                name,
                byte_to_char,
            )
        ]
        field_reads = [
            later
            for later in later_spans
            if _span_has_member_read(source, later, name, byte_to_char)
        ]
        key = ("address-taken-local", name)
        if address_uses and field_reads and key not in seen:
            seen.add(key)
            blockers.append({
                "kind": "address-taken-local",
                "local": name,
                "type": type_text,
                "definition_lines": [span.line_range[0], span.line_range[1]],
                "address_use_lines": [
                    address_uses[0].line_range[0],
                    address_uses[0].line_range[1],
                ],
                "read_lines": [
                    field_reads[0].line_range[0],
                    field_reads[0].line_range[1],
                ],
            })
    return blockers


def _later_same_scope_spans(
    spans: list[StatementSpan],
    start_idx: int,
    anchor: StatementSpan,
) -> list[StatementSpan]:
    out: list[StatementSpan] = []
    for cursor in range(start_idx, len(spans)):
        span = spans[cursor]
        if (
            span.scope_path != anchor.scope_path
            or span.scope_byte_range != anchor.scope_byte_range
        ):
            break
        out.append(span)
    return out


def _later_identifier_spans(
    source: str,
    spans: list[StatementSpan],
    start_idx: int,
    anchor: StatementSpan,
    name: str,
    byte_to_char: list[int],
) -> list[StatementSpan]:
    return [
        span
        for span in _later_same_scope_spans(spans, start_idx, anchor)
        if _span_mentions_identifier(source, span, name, byte_to_char)
    ]


def _span_has_address_taken_identifier(
    source: str,
    span: StatementSpan,
    name: str,
    byte_to_char: list[int],
) -> bool:
    raw = _span_source(source, span, byte_to_char)
    return re.search(r"(?<![A-Za-z_])&\s*" + re.escape(name) + r"\b", raw) is not None


def _span_has_member_read(
    source: str,
    span: StatementSpan,
    name: str,
    byte_to_char: list[int],
) -> bool:
    raw = _span_source(source, span, byte_to_char)
    return re.search(r"\b" + re.escape(name) + r"\s*(?:\.|->)\s*[A-Za-z_]\w*", raw) is not None


def _frame_local_blocker_label(blocker: dict) -> str:
    kind = blocker.get("kind")
    local = blocker.get("local")
    if kind == "address-taken-local" and local:
        return f"address-taken local `{local}`"
    if kind == "multi-use-local" and local:
        return f"multi-use local `{local}`"
    return str(kind or "unknown")


def _frame_local_initialized_candidate(
    source: str,
    spans: list[StatementSpan],
    idx: int,
    byte_to_char: list[int],
) -> tuple[str, str, str, str, tuple[StatementSpan, ...], StatementSpan, int] | None:
    span = spans[idx]
    if span.kind != "declaration":
        return None
    match = _SIMPLE_LOCAL_DECL_RE.match(_span_source(source, span, byte_to_char))
    if match is None:
        return None
    type_text = " ".join(match.group("type").split())
    name = match.group("name")
    expr = match.group("expr").strip()
    if not _is_simple_dematerialize_type(type_text):
        return None
    if not _safe_dematerialize_expr(expr):
        return None
    return (
        name,
        type_text,
        expr,
        "inline-initialized-local",
        (span,),
        span,
        idx + 1,
    )


def _frame_local_assigned_candidate(
    source: str,
    spans: list[StatementSpan],
    idx: int,
    byte_to_char: list[int],
) -> tuple[str, str, str, str, tuple[StatementSpan, ...], StatementSpan, int] | None:
    decl_span = spans[idx]
    if decl_span.kind != "declaration":
        return None
    match = _SIMPLE_LOCAL_BARE_DECL_RE.match(
        _span_source(source, decl_span, byte_to_char)
    )
    if match is None:
        return None
    type_text = " ".join(match.group("type").split())
    name = match.group("name")
    if not _is_simple_dematerialize_type(type_text):
        return None
    assign_idx = _find_next_executable_span(
        source,
        spans,
        idx + 1,
        decl_span,
        byte_to_char,
    )
    if assign_idx is None:
        return None
    assign_span = spans[assign_idx]
    if assign_span.kind != "expression_statement":
        return None
    assign = _SIMPLE_ASSIGN_RE.match(_span_source(source, assign_span, byte_to_char))
    if assign is None or assign.group("name") != name:
        return None
    expr = assign.group("expr").strip()
    if not _safe_dematerialize_expr(expr):
        return None
    return (
        name,
        type_text,
        expr,
        "inline-assigned-local",
        (decl_span, assign_span),
        assign_span,
        assign_idx + 1,
    )


def _find_next_executable_span(
    source: str,
    spans: list[StatementSpan],
    start_idx: int,
    anchor: StatementSpan,
    byte_to_char: list[int],
) -> int | None:
    _, anchor_end = _span_char_range(source, anchor, byte_to_char)
    for cursor in range(start_idx, len(spans)):
        span = spans[cursor]
        span_start, _ = _span_char_range(source, span, byte_to_char)
        if _has_preprocessor_between(source, anchor_end, span_start):
            return None
        if "{" in source[anchor_end:span_start] or "}" in source[anchor_end:span_start]:
            return None
        if span.scope_path != anchor.scope_path or span.scope_byte_range != anchor.scope_byte_range:
            return None
        if span.kind == "declaration":
            if not _is_inert_intervening_declaration(source, span, byte_to_char):
                return None
            continue
        return cursor
    return None


def _find_frame_local_use_index(
    source: str,
    spans: list[StatementSpan],
    start_idx: int,
    value_span: StatementSpan,
    name: str,
    byte_to_char: list[int],
) -> int | None:
    value_start, value_end = _span_char_range(source, value_span, byte_to_char)
    del value_start
    for cursor in range(start_idx, len(spans)):
        span = spans[cursor]
        span_start, _ = _span_char_range(source, span, byte_to_char)
        between = source[value_end:span_start]
        if _has_preprocessor_between(source, value_end, span_start):
            return None
        if "{" in between or "}" in between:
            return None
        if span.scope_path != value_span.scope_path or span.scope_byte_range != value_span.scope_byte_range:
            return None
        if span.kind == "declaration":
            if not _is_inert_intervening_declaration(source, span, byte_to_char):
                return None
            continue
        if not _span_mentions_identifier(source, span, name, byte_to_char):
            return None
        return cursor
    return None


def _frame_local_only_definition_and_use(
    source: str,
    *,
    body_span: tuple[int, int],
    name: str,
    definition_ranges: list[tuple[int, int]],
    use_range: tuple[int, int],
) -> bool:
    use_text = source[use_range[0]:use_range[1]]
    if _identifier_count(use_text, name) != 1:
        return False
    body_start, body_end = body_span
    relative_excluded = [
        (max(0, start - body_start), min(body_end, end) - body_start)
        for start, end in [*definition_ranges, use_range]
    ]
    return _identifier_count_excluding_ranges(
        source[body_start:body_end],
        name,
        relative_excluded,
    ) == 0


def _rewrite_frame_local_use(
    source: str,
    span: StatementSpan,
    *,
    name: str,
    type_text: str,
    expr: str,
    byte_to_char: list[int],
) -> tuple[int, int, str, str] | None:
    if span.kind != "expression_statement":
        return None
    raw = _span_source(source, span, byte_to_char)
    if re.search(r"(?<![A-Za-z_])&\s*" + re.escape(name) + r"\b", raw):
        return None
    casted_expr = f"(({type_text}) ({expr}))"
    rhs_rewrite = _rewrite_frame_local_rhs_use(
        source,
        span,
        raw,
        name=name,
        replacement=casted_expr,
        byte_to_char=byte_to_char,
    )
    if rhs_rewrite is not None:
        return rhs_rewrite
    return _rewrite_frame_local_call_arg_use(
        source,
        span,
        raw,
        name=name,
        replacement=casted_expr,
        byte_to_char=byte_to_char,
    )


def _rewrite_frame_local_rhs_use(
    source: str,
    span: StatementSpan,
    raw: str,
    *,
    name: str,
    replacement: str,
    byte_to_char: list[int],
) -> tuple[int, int, str, str] | None:
    match = _SIMPLE_RHS_ASSIGN_USE_RE.match(raw)
    if match is None or match.group("rhs") != name or match.group("lhs") == name:
        return None
    span_start, _ = _span_char_range(source, span, byte_to_char)
    return (
        span_start + match.start("rhs"),
        span_start + match.end("rhs"),
        replacement,
        "assignment-rhs",
    )


def _rewrite_frame_local_call_arg_use(
    source: str,
    span: StatementSpan,
    raw: str,
    *,
    name: str,
    replacement: str,
    byte_to_char: list[int],
) -> tuple[int, int, str, str] | None:
    call = _SIMPLE_CALL_STMT_RE.match(raw)
    if call is None:
        return None
    open_rel = raw.find("(", call.end() - 1)
    if open_rel < 0:
        return None
    close_rel = _find_matching_paren(raw, open_rel)
    if close_rel is None or raw[close_rel + 1:].strip() != ";":
        return None
    args_text = raw[open_rel + 1:close_rel]
    span_start, _ = _span_char_range(source, span, byte_to_char)
    args = _split_top_level_args_with_ranges(
        args_text,
        absolute_start=span_start + open_rel + 1,
    )
    matching_args = [
        (arg_start, arg_end)
        for arg, arg_start, arg_end in args
        if arg == name
    ]
    if len(matching_args) != 1:
        return None
    for arg, _arg_start, _arg_end in args:
        if arg == name:
            continue
        if not _safe_dematerialize_expr(arg):
            return None
    arg_start, arg_end = matching_args[0]
    return arg_start, arg_end, replacement, "call-argument"


def _balanced_expression_delimiters(text: str) -> bool:
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for char in text:
        if char in pairs:
            stack.append(pairs[char])
        elif char in closing:
            if not stack or stack.pop() != char:
                return False
    return not stack


def _probe_frame_reservation_pad_stack(
    source: str,
    body: str,
    body_start: int,
    bytes_: int,
) -> LifetimeLayoutProbe | None:
    existing = re.search(
        r"(?m)^([ \t]*)PAD_STACK\(\s*(0x[0-9A-Fa-f]+|\d+)\s*\);\n?",
        body,
    )
    if existing is not None:
        previous = int(existing.group(2), 0)
        if previous == bytes_:
            return None
        indent = existing.group(1)
        replacement = f"{indent}PAD_STACK({bytes_});\n"
        return LifetimeLayoutProbe(
            label=f"frame-reservation-pad-stack-{bytes_}",
            operator="frame-reservation-pad-stack",
            description=(
                f"Replace existing PAD_STACK({previous}) with PAD_STACK({bytes_}) "
                "to test an implicit no-access frame reservation."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                existing.start(),
                existing.end(),
                replacement,
            ),
            provenance={
                "kind": "frame-reservation-pad-stack",
                "bytes": bytes_,
                "action": "replace",
                "previous_bytes": previous,
            },
        )

    insert_rel, indent = _pad_stack_insert_position(body)
    if insert_rel is None:
        return None
    line = f"{indent}PAD_STACK({bytes_});\n"
    return LifetimeLayoutProbe(
        label=f"frame-reservation-pad-stack-{bytes_}",
        operator="frame-reservation-pad-stack",
        description=(
            f"Insert PAD_STACK({bytes_}) to test an implicit no-access "
            "frame reservation."
        ),
        source_text=(
            source[: body_start + insert_rel]
            + line
            + source[body_start + insert_rel :]
        ),
        provenance={
            "kind": "frame-reservation-pad-stack",
            "bytes": bytes_,
            "action": "insert",
        },
    )


def _probe_frame_reservation_pad_stack_delta(
    source: str,
    body: str,
    body_start: int,
    delta: int,
) -> LifetimeLayoutProbe | None:
    existing = re.search(
        r"(?m)^([ \t]*)PAD_STACK\(\s*(0x[0-9A-Fa-f]+|\d+)\s*\);\n?",
        body,
    )
    if delta > 0:
        if existing is not None:
            previous = int(existing.group(2), 0)
            bytes_ = previous + delta
            indent = existing.group(1)
            replacement = f"{indent}PAD_STACK({bytes_});\n"
            return LifetimeLayoutProbe(
                label=f"frame-reservation-pad-stack-{bytes_}",
                operator="frame-reservation-pad-stack",
                description=(
                    f"Increase existing PAD_STACK({previous}) by {delta} "
                    "byte(s) to test a larger implicit no-access frame "
                    "reservation."
                ),
                source_text=_replace_body_slice(
                    source,
                    body_start,
                    existing.start(),
                    existing.end(),
                    replacement,
                ),
                provenance={
                    "kind": "frame-reservation-pad-stack",
                    "bytes": bytes_,
                    "action": "increase",
                    "previous_bytes": previous,
                    "delta": delta,
                },
            )

        insert_rel, indent = _pad_stack_insert_position(body)
        if insert_rel is None:
            return None
        line = f"{indent}PAD_STACK({delta});\n"
        return LifetimeLayoutProbe(
            label=f"frame-reservation-pad-stack-{delta}",
            operator="frame-reservation-pad-stack",
            description=(
                f"Insert PAD_STACK({delta}) to test an implicit no-access "
                "frame reservation."
            ),
            source_text=(
                source[: body_start + insert_rel]
                + line
                + source[body_start + insert_rel :]
            ),
            provenance={
                "kind": "frame-reservation-pad-stack",
                "bytes": delta,
                "action": "insert",
                "delta": delta,
            },
        )

    if existing is None:
        return None
    previous = int(existing.group(2), 0)
    remove_bytes = abs(delta)
    indent = existing.group(1)
    if previous <= remove_bytes:
        return LifetimeLayoutProbe(
            label=f"frame-reservation-pad-stack-remove-{previous}",
            operator="frame-reservation-pad-stack",
            description=(
                f"Remove existing PAD_STACK({previous}) to test removing an "
                "implicit no-access frame reservation."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                existing.start(),
                existing.end(),
                "",
            ),
            provenance={
                "kind": "frame-reservation-pad-stack",
                "action": "remove",
                "previous_bytes": previous,
                "delta": delta,
            },
        )

    bytes_ = previous - remove_bytes
    replacement = f"{indent}PAD_STACK({bytes_});\n"
    return LifetimeLayoutProbe(
        label=f"frame-reservation-pad-stack-{bytes_}",
        operator="frame-reservation-pad-stack",
        description=(
            f"Decrease existing PAD_STACK({previous}) by {remove_bytes} "
            "byte(s) to test a smaller implicit no-access frame reservation."
        ),
        source_text=_replace_body_slice(
            source,
            body_start,
            existing.start(),
            existing.end(),
            replacement,
        ),
        provenance={
            "kind": "frame-reservation-pad-stack",
            "bytes": bytes_,
            "action": "decrease",
            "previous_bytes": previous,
            "delta": delta,
        },
    )


def _pad_stack_insert_position(body: str) -> tuple[int | None, str]:
    cursor = 0
    insert_rel: int | None = None
    indent = "    "
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            if insert_rel is not None:
                break
            cursor += len(line)
            continue
        match = _LOCAL_DECL_RE.match(line)
        if match is not None:
            indent_match = re.match(r"[ \t]*", line)
            indent = "" if indent_match is None else indent_match.group(0)
            insert_rel = cursor + len(line)
            cursor += len(line)
            continue
        if insert_rel is None:
            indent_match = re.match(r"[ \t]*", line)
            indent = "" if indent_match is None else indent_match.group(0)
            insert_rel = cursor
        break
    if insert_rel is None:
        insert_rel = len(body)
    return insert_rel, indent


def _scoped_identifier_types(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> dict[str, str]:
    types: dict[str, str] = {}
    params = _function_param_text(source, function, body_start)
    if params is not None:
        for part in _split_top_level_args(params):
            parsed = _parse_simple_decl(part)
            if parsed is not None:
                name, typ = parsed
                types[name] = typ
    for match in re.finditer(
        r"(?m)^[ \t]*(?P<decl>(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w+)(?:\s*\*)*"
        r"\s+[A-Za-z_]\w*)\s*(?:[=;,\[])",
        body,
    ):
        parsed = _parse_simple_decl(match.group("decl"))
        if parsed is not None:
            name, typ = parsed
            types[name] = _normalize_type_spelling(typ)
    return types


def _function_param_text(
    source: str,
    function: str,
    body_start: int,
) -> str | None:
    prefix = source[:body_start]
    matches = list(re.finditer(rf"\b{re.escape(function)}\s*\(", prefix))
    if not matches:
        return None
    open_paren = prefix.find("(", matches[-1].start())
    close_paren = _find_matching_paren(source, open_paren)
    if close_paren is None or close_paren > body_start:
        return None
    return source[open_paren + 1:close_paren]


def _parse_simple_decl(text: str) -> tuple[str, str] | None:
    if "(*" in text:
        return None
    text = re.sub(r"\s+", " ", text.strip())
    match = re.match(
        r"^(?P<type>(?:const\s+|volatile\s+)*(?:f32|float|double|s32|u32|int|"
        r"struct\s+[A-Za-z_]\w*|[A-Za-z_]\w+)(?:\s*\*)*)\s+"
        r"(?P<name>[A-Za-z_]\w*)$",
        text,
    )
    if match is None:
        return None
    typ = _normalize_type_spelling(match.group("type"))
    return match.group("name"), typ


def _infer_call_arg_temp_type(expr: str, scoped_types: dict[str, str]) -> str:
    names = set(re.findall(r"\b[A-Za-z_]\w*\b", expr))
    referenced_types = {scoped_types[name] for name in names if name in scoped_types}
    if "double" in referenced_types:
        return "double"
    if "f32" in referenced_types:
        return "f32"
    if "float" in referenced_types or re.search(r"\d+\.\d*|\d*\.\d+|\d+\.?f\b", expr):
        return "float"
    return "int"


@dataclass(frozen=True)
class _DeclLine:
    start: int
    end: int
    indent: str
    type_name: str
    name: str
    text: str
    depth: int


@dataclass(frozen=True)
class _SiblingCounterLoop:
    decl: _DeclLine
    loop_start: int
    loop_close: int
    shape: str
    call_symbol: str
    indexed_by_counter: bool


def _probe_declaration_order(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    hoist_before, hoist_after = _probe_nested_loop_counter_hoist(
        source,
        body,
        body_start,
        function,
    )
    if hoist_before is not None:
        probes.append(hoist_before)
    probes.extend(_probe_sibling_loop_counter_hoists(source, body, body_start, function))
    adjacent = _probe_adjacent_decl_swap(source, body, body_start, function)
    if adjacent is not None:
        probes.append(adjacent)
    loop_type = _probe_loop_counter_type(source, body, body_start, function)
    if loop_type is not None:
        probes.append(loop_type)
    if hoist_after is not None:
        probes.append(hoist_after)
    return probes


def _probe_expression_shape(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    assignment = _probe_assignment_expression_cse_removal(
        source,
        body,
        body_start,
        function,
    )
    if assignment is not None:
        probes.append(assignment)
    distance = _probe_distance_component_temps(source, body, body_start, function)
    if distance is not None:
        probes.append(distance)
    abs_discriminator = _probe_abs_branch_discriminator_split(
        source,
        body,
        body_start,
        function,
    )
    if abs_discriminator is not None:
        probes.append(abs_discriminator)
    return probes


def _iter_decl_lines(body: str) -> list[_DeclLine]:
    decls: list[_DeclLine] = []
    depth = 0
    cursor = 0
    for line in body.splitlines(keepends=True):
        line_depth = depth
        match = _DECL_LINE_RE.match(line)
        if match is not None:
            indent, type_name, name = match.groups()
            decls.append(
                _DeclLine(
                    start=cursor,
                    end=cursor + len(line),
                    indent=indent,
                    type_name=type_name.replace(" ", ""),
                    name=name,
                    text=line,
                    depth=line_depth,
                )
            )
        for char in line:
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
        cursor += len(line)
    return decls


def _probe_adjacent_decl_swap(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    top_decls = [decl for decl in _iter_decl_lines(body) if decl.depth == 0]
    for left, right in zip(top_decls, top_decls[1:]):
        if left.end != right.start or left.indent != right.indent:
            continue
        mutated = _replace_body_slice(
            source,
            body_start,
            left.start,
            right.end,
            right.text + left.text,
        )
        return LifetimeLayoutProbe(
            label="adjacent-decl-swap-0",
            operator="declaration-order",
            description=(
                f"Swap adjacent function-scope locals `{left.name}` and "
                f"`{right.name}` to test allocator role order."
            ),
            source_text=mutated,
            provenance={
                "kind": "adjacent-decl-swap",
                "first": left.name,
                "second": right.name,
            },
        )
    return None


def _probe_loop_counter_type(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    decls = _iter_decl_lines(body)
    first_width_decl = next(
        (decl for decl in decls if decl.type_name in {"int", "s32", "u32"}),
        None,
    )
    for decl in decls:
        if decl.type_name not in {"int", "s32"}:
            continue
        if first_width_decl == decl:
            continue
        if _find_loop_using_counter(body, decl.end, decl.name) is None:
            continue
        new_type = "int" if decl.type_name == "s32" else "s32"
        replacement = f"{decl.indent}{new_type} {decl.name};\n"
        return LifetimeLayoutProbe(
            label="loop-counter-type-0",
            operator="loop-counter-type",
            description=(
                f"Change loop counter `{decl.name}` type "
                f"{decl.type_name} -> {new_type}."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                decl.start,
                decl.end,
                replacement,
            ),
            provenance={
                "kind": "loop-counter-type",
                "counter": decl.name,
                "from_type": decl.type_name,
                "to_type": new_type,
            },
        )
    return None


@dataclass(frozen=True)
class _IndexedLoopUse:
    loop_start: int
    loop_end: int
    loop_open: int
    loop_close: int
    loop_indent: str
    counter: str
    bound: str
    bound_start: int
    bound_end: int
    line_start: int
    line_end: int
    line: str
    line_indent: str
    base: str
    base_start: int
    base_end: int
    index_expr: str
    index_start: int
    index_end: int
    address_start: int
    address_end: int
    indexed_end: int
    decl_type: str | None


@dataclass(frozen=True)
class _PointerWalkLoopUse:
    loop_start: int
    loop_close: int
    loop_indent: str
    counter: str
    bound: str
    bound_start: int
    bound_end: int
    condition_start: int
    condition_end: int
    increment_start: int
    increment_end: int
    line_start: int
    line_end: int
    line: str
    line_indent: str
    base: str
    base_start: int
    base_end: int
    index_expr: str
    index_start: int
    index_end: int
    indexed_start: int
    indexed_end: int
    base_type: str
    value_type: str


@dataclass(frozen=True)
class _PointerBaseCallLoopUse:
    loop_start: int
    loop_close: int
    loop_indent: str
    counter: str
    bound: str
    condition_start: int
    condition_end: int
    increment_end: int
    line_start: int
    line_end: int
    line: str
    line_indent: str
    base: str
    base_start: int
    base_end: int
    base_type: str
    value_type: str


@dataclass(frozen=True)
class _IndexedStructPointerCandidate:
    pointer: str
    declaration: str
    decl_start: int
    decl_end: int
    base_expression: str
    index_expression: str
    subindex_expression: str | None
    direct_expression: str
    access_mode: str


@dataclass(frozen=True)
class _IndexedStructPointerFieldUse:
    start: int
    end: int
    field: str
    syntax: str
    replacement: str
    source_lines: tuple[int, int]


@dataclass(frozen=True)
class _IndexedStructDirectFieldUse:
    start: int
    end: int
    line_start: int
    line_end: int
    line_indent: str
    line: str
    expression: str
    base_expression: str
    index_expression: str
    subindex_expression: str | None
    direct_expression: str
    field: str
    source_lines: tuple[int, int]


def _probe_indexed_pointer_loop(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    use = _find_indexed_pointer_loop_use(source, body, body_start)
    if use is None:
        return []
    scoped_types = _scoped_identifier_types(source, body, body_start, function)
    probes: list[LifetimeLayoutProbe] = []

    loop_text = source[body_start + use.loop_start:body_start + use.loop_close + 1]
    rel_bound_start = use.bound_start - use.loop_start
    rel_bound_end = use.bound_end - use.loop_start
    bounded_loop = (
        loop_text[:rel_bound_start]
        + "ll_probe_loop_bound_0"
        + loop_text[rel_bound_end:]
    )
    bounded_replacement = (
        f"{use.loop_indent}{{\n"
        f"{use.loop_indent}    int ll_probe_loop_bound_0 = {use.bound};\n"
        f"{_indent_block_lines(bounded_loop, use.loop_indent)}"
        f"{use.loop_indent}}}"
    )
    probes.append(
        LifetimeLayoutProbe(
            label="indexed-pointer-loop-bound-local-0",
            operator="indexed-pointer-loop",
            description=(
                f"Cache loop bound `{use.bound}` in a scoped local before the "
                f"indexed pointer loop over `{use.base}`."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.loop_start,
                use.loop_close + 1,
                bounded_replacement,
            ),
            provenance={
                "kind": "indexed-pointer-loop",
                "variant": "bound-local",
                "counter": use.counter,
                "base": use.base,
                "index_expr": use.index_expr,
                "bound": use.bound,
            },
        )
    )

    if use.index_expr != use.counter:
        index_line = (
            use.line[:use.index_start]
            + "ll_probe_index_0"
            + use.line[use.index_end:]
        )
        index_replacement = (
            f"{use.line_indent}int ll_probe_index_0 = {use.index_expr};\n"
            f"{index_line}"
        )
        probes.append(
            LifetimeLayoutProbe(
                label="indexed-pointer-loop-index-temp-0",
                operator="indexed-pointer-loop",
                description=(
                    f"Name indexed pointer loop index expression `{use.index_expr}` "
                    f"before using `{use.base}`."
                ),
                source_text=_replace_body_slice(
                    source,
                    body_start,
                    use.line_start,
                    use.line_end,
                    index_replacement,
                ),
                provenance={
                    "kind": "indexed-pointer-loop",
                    "variant": "index-temp",
                    "counter": use.counter,
                    "base": use.base,
                    "index_expr": use.index_expr,
                    "bound": use.bound,
                },
            )
        )

    base_type = scoped_types.get(use.base)
    if base_type:
        base_line = (
            use.line[:use.base_start]
            + "ll_probe_base_0"
            + use.line[use.base_end:]
        )
        base_replacement = (
            f"{use.line_indent}{base_type} ll_probe_base_0 = {use.base};\n"
            f"{base_line}"
        )
        probes.append(
            LifetimeLayoutProbe(
                label="indexed-pointer-loop-base-alias-0",
                operator="indexed-pointer-loop",
                description=(
                    f"Alias indexed pointer loop base `{use.base}` inside the "
                    "loop body."
                ),
                source_text=_replace_body_slice(
                    source,
                    body_start,
                    use.line_start,
                    use.line_end,
                    base_replacement,
                ),
                provenance={
                    "kind": "indexed-pointer-loop",
                    "variant": "base-alias",
                    "counter": use.counter,
                    "base": use.base,
                    "index_expr": use.index_expr,
                    "bound": use.bound,
                },
            )
        )

    if use.decl_type is not None and use.indexed_end > use.address_end:
        address_expr = use.line[use.address_start:use.address_end]
        address_type = _add_pointer_to_type(use.decl_type)
        address_line = (
            use.line[:use.address_start]
            + "ll_probe_addr_0"
            + use.line[use.address_end:]
        )
        address_replacement = (
            f"{use.line_indent}{address_type} ll_probe_addr_0 = {address_expr};\n"
            f"{address_line}"
        )
        probes.append(
            LifetimeLayoutProbe(
                label="indexed-pointer-loop-address-temp-0",
                operator="indexed-pointer-loop",
                description=(
                    f"Name computed pointer address `{address_expr}` before "
                    "loading the indexed loop value."
                ),
                source_text=_replace_body_slice(
                    source,
                    body_start,
                    use.line_start,
                    use.line_end,
                    address_replacement,
                ),
                provenance={
                    "kind": "indexed-pointer-loop",
                    "variant": "address-temp",
                    "counter": use.counter,
                    "base": use.base,
                    "index_expr": use.index_expr,
                    "bound": use.bound,
                },
            )
        )

    return probes


def scan_indexed_struct_pointer_probes(
    source_text: str,
    function: str,
    max_probes: int = 12,
) -> tuple[list[LifetimeLayoutProbe], dict]:
    """Scan for safe materialized struct pointers that can be de-indexed."""
    body_span = _find_function_body_span(source_text, function)
    if body_span is None:
        return [], _indexed_struct_pointer_status(
            "indexed-struct-hint-unavailable",
            "checkdiff hint could not be associated with a supported source "
            "pointer initializer",
            supported_candidate_count=0,
            rejected_candidate_count=0,
        )

    body_start, body_end = body_span
    body = source_text[body_start:body_end]
    probes: list[LifetimeLayoutProbe] = []
    supported_candidate_count = 0
    rejected_candidate_count = 0
    safe_candidate_count = 0

    for candidate in _indexed_struct_pointer_candidates(body, body_start):
        supported_candidate_count += 1
        candidate_body_end = _indexed_struct_enclosing_block_end(
            source_text,
            body_start,
            body_end,
            candidate.decl_start,
        )
        probe = _indexed_struct_pointer_probe_for_candidate(
            source_text,
            candidate,
            body_start=body_start,
            body_end=candidate_body_end,
            label_index=safe_candidate_count,
        )
        if probe is None:
            rejected_candidate_count += 1
            continue
        safe_candidate_count += 1
        if len(probes) < max_probes:
            probes.append(probe)

    direct_probes, direct_supported, direct_rejected, direct_safe = (
        _indexed_struct_direct_scalar_split_probes(
            source_text,
            body,
            body_start,
            body_end,
            function,
            label_start=safe_candidate_count,
            max_probes=max(0, max_probes - len(probes)),
        )
    )
    supported_candidate_count += direct_supported
    rejected_candidate_count += direct_rejected
    safe_candidate_count += direct_safe
    probes.extend(direct_probes)

    if supported_candidate_count == 0:
        return [], _indexed_struct_pointer_status(
            "indexed-struct-hint-unavailable",
            "checkdiff hint could not be associated with a supported source "
            "pointer initializer",
            supported_candidate_count=supported_candidate_count,
            rejected_candidate_count=rejected_candidate_count,
        )
    if safe_candidate_count == 0:
        return [], _indexed_struct_pointer_status(
            "no-safe-materialized-pointer",
            "source scan found materialized pointers, but all violated safety rules",
            supported_candidate_count=supported_candidate_count,
            rejected_candidate_count=rejected_candidate_count,
        )
    return probes, _indexed_struct_pointer_status(
        None,
        "source scan generated safe indexed struct pointer probes",
        supported_candidate_count=supported_candidate_count,
        rejected_candidate_count=rejected_candidate_count,
    )


def generate_indexed_struct_pointer_probes(
    source_text: str,
    function: str,
    max_probes: int = 12,
) -> list[LifetimeLayoutProbe]:
    probes, _status = scan_indexed_struct_pointer_probes(
        source_text,
        function,
        max_probes=max_probes,
    )
    return probes


_INDEXED_STRUCT_POINTER_DECL_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?P<type>(?:(?:const|volatile)\s+)*(?:struct\s+)?[A-Za-z_]\w*"
    r"(?:\s+(?:const|volatile))?)"
    r"\s*\*\s*(?P<pointer>[A-Za-z_]\w*)\s*=\s*"
    r"(?P<initializer>[^;\n]+);[ \t]*$"
)
_INDEXED_STRUCT_DIRECT_FIELD_RE = re.compile(
    r"(?P<direct>"
    r"(?P<base>\b[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)"
    r"\s*\[\s*(?P<index>[^\[\]\n;]+)\s*\]\s*"
    r"(?:\[\s*(?P<subindex>[^\[\]\n;]+)\s*\])?"
    r")\s*\.\s*(?P<field>[A-Za-z_]\w*)"
)


def _indexed_struct_pointer_status(
    blocker: str | None,
    reason: str,
    *,
    supported_candidate_count: int,
    rejected_candidate_count: int,
) -> dict:
    return {
        "blocker": blocker,
        "reason": reason,
        "supported_candidate_count": supported_candidate_count,
        "rejected_candidate_count": rejected_candidate_count,
    }


def _indexed_struct_pointer_candidates(
    body: str,
    body_start: int,
) -> list[_IndexedStructPointerCandidate]:
    candidates: list[_IndexedStructPointerCandidate] = []
    cursor = 0
    code_body = _mask_c_non_code_text(body)
    body_lines = body.splitlines(keepends=True)
    code_lines = code_body.splitlines(keepends=True)
    for line, code_line in zip(body_lines, code_lines, strict=True):
        code_line_text = code_line[:-1] if code_line.endswith("\n") else code_line
        match = _INDEXED_STRUCT_POINTER_DECL_RE.match(code_line_text)
        if match is not None:
            parsed = _parse_indexed_struct_pointer_initializer(
                match.group("initializer").strip()
            )
            if parsed is not None:
                (
                    base_expression,
                    index_expression,
                    subindex_expression,
                    direct_expression,
                    access_mode,
                ) = parsed
                candidates.append(
                    _IndexedStructPointerCandidate(
                        pointer=match.group("pointer"),
                        declaration=line.strip(),
                        decl_start=body_start + cursor,
                        decl_end=body_start + cursor + len(line),
                        base_expression=base_expression,
                        index_expression=index_expression,
                        subindex_expression=subindex_expression,
                        direct_expression=direct_expression,
                        access_mode=access_mode,
                    )
                )
        cursor += len(line)
    return candidates


def _indexed_struct_enclosing_block_end(
    source: str,
    body_start: int,
    body_end: int,
    offset: int,
) -> int:
    region = source[body_start:body_end]
    code_region = _mask_c_non_code_text(region)
    relative_offset = max(0, min(len(code_region), offset - body_start))
    stack: list[int] = []
    for idx, char in enumerate(code_region[:relative_offset]):
        if char == "{":
            stack.append(idx)
        elif char == "}" and stack:
            stack.pop()
    if not stack:
        return body_end

    target_depth = len(stack)
    for idx in range(relative_offset, len(code_region)):
        char = code_region[idx]
        if char == "{":
            stack.append(idx)
        elif char == "}" and stack:
            stack.pop()
            if len(stack) < target_depth:
                return body_start + idx
    return body_end


def _parse_indexed_struct_pointer_initializer(
    initializer: str,
) -> tuple[str, str, str | None, str, str] | None:
    if initializer.startswith("&"):
        indexed = _parse_indexed_struct_address_expression(initializer[1:].strip())
        if indexed is None:
            return None
        base_expression, index_expression, subindex_expression = indexed
        direct_expression = f"{base_expression}[{index_expression}]"
        if subindex_expression is not None:
            direct_expression += f"[{subindex_expression}]"
        return (
            base_expression,
            index_expression,
            subindex_expression,
            direct_expression,
            "struct-value",
        )

    plus = _split_top_level_plus(initializer)
    if plus is None:
        return None
    base_expression, index_expression = plus
    return (
        base_expression,
        index_expression,
        None,
        f"{base_expression} + {index_expression}",
        "pointer-expression",
    )


def _parse_indexed_struct_address_expression(
    expression: str,
) -> tuple[str, str, str | None] | None:
    match = re.match(
        r"^(?P<base>[^\[\]]+?)\s*"
        r"\[\s*(?P<index>[^\[\]]+)\s*\]\s*"
        r"(?:\[\s*(?P<subindex>[^\[\]]+)\s*\])?\s*$",
        expression,
    )
    if match is None:
        return None
    return (
        match.group("base").strip(),
        match.group("index").strip(),
        (
            match.group("subindex").strip()
            if match.group("subindex") is not None
            else None
        ),
    )


def _split_top_level_plus(expression: str) -> tuple[str, str] | None:
    paren_depth = 0
    bracket_depth = 0
    plus_positions: list[int] = []
    for idx, char in enumerate(expression):
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "+" and paren_depth == 0 and bracket_depth == 0:
            plus_positions.append(idx)
    if len(plus_positions) != 1:
        return None
    split = plus_positions[0]
    left = expression[:split].strip()
    right = expression[split + 1:].strip()
    if not left or not right:
        return None
    return left, right


def _indexed_struct_pointer_probe_for_candidate(
    source: str,
    candidate: _IndexedStructPointerCandidate,
    *,
    body_start: int,
    body_end: int,
    label_index: int,
) -> LifetimeLayoutProbe | None:
    if _offset_inside_preprocessor_region(source, body_start, candidate.decl_start):
        return None

    expressions = [
        candidate.base_expression,
        candidate.index_expression,
    ]
    if candidate.subindex_expression is not None:
        expressions.append(candidate.subindex_expression)
    if not all(
        _indexed_struct_expression_is_side_effect_free(expr) for expr in expressions
    ):
        return None

    field_uses = _indexed_struct_pointer_field_uses(
        source,
        candidate,
        candidate.decl_end,
        body_end,
    )
    if not field_uses:
        return None

    affected_end = max(field_use.end for field_use in field_uses)
    affected_region = source[candidate.decl_end:affected_end]
    if _indexed_struct_expression_inputs_mutated(
        affected_region,
        candidate.base_expression,
        candidate.index_expression,
        candidate.subindex_expression,
    ):
        return None
    if _region_has_preprocessor_directive(source[candidate.decl_start:affected_end]):
        return None

    source_line_start = _line_col(source, candidate.decl_start)[0]
    source_line_end = max(field_use.source_lines[1] for field_use in field_uses)
    replacements = [(candidate.decl_start, candidate.decl_end, "")]
    replacements.extend(
        (field_use.start, field_use.end, field_use.replacement)
        for field_use in field_uses
    )
    provenance = {
        "kind": "indexed-struct-pointer",
        "diagnostic": "indexed_struct_pointer_materialization",
        "pointer": candidate.pointer,
        "source_lines": [source_line_start, source_line_end],
        "declaration": candidate.declaration,
        "base_expression": candidate.base_expression,
        "index_expression": candidate.index_expression,
        "direct_expression": candidate.direct_expression,
        "field_uses": [
            {
                "field": field_use.field,
                "syntax": field_use.syntax,
                "source_lines": list(field_use.source_lines),
            }
            for field_use in field_uses
        ],
        "split_first_field": False,
    }
    if candidate.subindex_expression is not None:
        provenance["subindex_expression"] = candidate.subindex_expression

    return LifetimeLayoutProbe(
        label=f"indexed-struct-pointer-{label_index}",
        operator="indexed-struct-pointer",
        description=(
            f"Rewrite materialized struct pointer `{candidate.pointer}` uses "
            f"through `{candidate.direct_expression}`."
        ),
        source_text=_replace_absolute_slices(source, replacements),
        provenance=provenance,
    )


def _indexed_struct_direct_scalar_split_probes(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
    *,
    label_start: int,
    max_probes: int,
) -> tuple[list[LifetimeLayoutProbe], int, int, int]:
    uses_by_direct: dict[
        tuple[str, str, str | None, str],
        list[_IndexedStructDirectFieldUse],
    ] = {}
    for use in _indexed_struct_direct_field_uses(source, body_start, body_end):
        key = (
            use.base_expression,
            use.index_expression,
            use.subindex_expression,
            use.direct_expression,
        )
        uses_by_direct.setdefault(key, []).append(use)

    probes: list[LifetimeLayoutProbe] = []
    supported_candidate_count = 0
    rejected_candidate_count = 0
    safe_candidate_count = 0
    scoped_types = _scoped_identifier_types(source, body, body_start, function)
    for group_uses in uses_by_direct.values():
        if len(group_uses) < 2:
            continue
        supported_candidate_count += 1
        probe = _indexed_struct_direct_scalar_split_probe_for_group(
            source,
            body,
            group_uses,
            body_start=body_start,
            scoped_types=scoped_types,
            label_index=label_start + safe_candidate_count,
        )
        if probe is None:
            rejected_candidate_count += 1
            continue
        safe_candidate_count += 1
        if len(probes) < max_probes:
            probes.append(probe)
    return (
        probes,
        supported_candidate_count,
        rejected_candidate_count,
        safe_candidate_count,
    )


def _indexed_struct_direct_field_uses(
    source: str,
    body_start: int,
    body_end: int,
) -> list[_IndexedStructDirectFieldUse]:
    body = source[body_start:body_end]
    code_body = _mask_c_non_code_text(body)
    uses: list[_IndexedStructDirectFieldUse] = []
    for match in _INDEXED_STRUCT_DIRECT_FIELD_RE.finditer(code_body):
        start = body_start + match.start()
        end = body_start + match.end()
        direct_start = body_start + match.start("direct")
        direct_end = body_start + match.end("direct")
        if not _indexed_struct_field_use_is_standalone(
            code_body,
            match.start(),
        ):
            continue
        if _indexed_struct_field_use_is_address_taken(code_body, match.start()):
            continue
        if _indexed_struct_direct_field_use_is_lvalue(code_body, match.end()):
            continue
        if _offset_inside_preprocessor_region(source, body_start, start):
            continue
        expressions = [
            source[body_start + match.start("base") : body_start + match.end("base")],
            source[
                body_start + match.start("index") : body_start + match.end("index")
            ],
        ]
        if match.group("subindex") is not None:
            expressions.append(
                source[
                    body_start + match.start("subindex") : body_start
                    + match.end("subindex")
                ]
            )
        if not all(
            _indexed_struct_expression_is_side_effect_free(expr)
            for expr in expressions
        ):
            continue

        line_start = source.rfind("\n", 0, start) + 1
        line_end = source.find("\n", end)
        if line_end < 0:
            line_end = len(source)
        else:
            line_end += 1
        line = source[line_start:line_end]
        indent_match = re.match(r"[ \t]*", line)
        line_indent = "" if indent_match is None else indent_match.group(0)
        start_line = _line_col(source, start)[0]
        end_line = _line_col(source, max(start, end - 1))[0]
        uses.append(
            _IndexedStructDirectFieldUse(
                start=start,
                end=end,
                line_start=line_start,
                line_end=line_end,
                line_indent=line_indent,
                line=line,
                expression=source[start:end],
                base_expression=source[
                    body_start + match.start("base") : body_start
                    + match.end("base")
                ].strip(),
                index_expression=source[
                    body_start + match.start("index") : body_start
                    + match.end("index")
                ].strip(),
                subindex_expression=(
                    source[
                        body_start + match.start("subindex") : body_start
                        + match.end("subindex")
                    ].strip()
                    if match.group("subindex") is not None
                    else None
                ),
                direct_expression=source[direct_start:direct_end].strip(),
                field=match.group("field"),
                source_lines=(start_line, end_line),
            )
        )
    return uses


def _indexed_struct_direct_scalar_split_probe_for_group(
    source: str,
    body: str,
    group_uses: list[_IndexedStructDirectFieldUse],
    *,
    body_start: int,
    scoped_types: dict[str, str],
    label_index: int,
) -> LifetimeLayoutProbe | None:
    group_uses = sorted(group_uses, key=lambda use: (use.start, use.end))
    first_use = group_uses[0]
    affected_end = max(use.end for use in group_uses)
    affected_region = source[first_use.end:affected_end]
    if _indexed_struct_expression_inputs_mutated(
        affected_region,
        first_use.base_expression,
        first_use.index_expression,
        first_use.subindex_expression,
    ):
        return None
    if _region_has_preprocessor_directive(source[first_use.line_start:affected_end]):
        return None

    scalar_type = _infer_indexed_struct_direct_scalar_type(
        first_use,
        scoped_types,
    )
    temp_name = _unique_indexed_struct_probe_name(
        source,
        "ll_probe_indexed_field",
    )
    line_relative_start = first_use.start - first_use.line_start
    line_relative_end = first_use.end - first_use.line_start
    rewritten_line = (
        first_use.line[:line_relative_start]
        + temp_name
        + first_use.line[line_relative_end:]
    )
    declaration_insert_rel, declaration_indent = _pad_stack_insert_position(body)
    declaration_insert = body_start + (declaration_insert_rel or 0)
    if first_use.line_start < declaration_insert:
        replacements = [
            (
                first_use.line_start,
                first_use.line_end,
                (
                    f"{first_use.line_indent}{scalar_type} {temp_name} = "
                    f"{first_use.expression};\n"
                    f"{rewritten_line}"
                ),
            )
        ]
    else:
        replacements = [
            (
                declaration_insert,
                declaration_insert,
                f"{declaration_indent}{scalar_type} {temp_name};\n",
            ),
            (
                first_use.line_start,
                first_use.line_end,
                (
                    f"{first_use.line_indent}{temp_name} = "
                    f"{first_use.expression};\n"
                    f"{rewritten_line}"
                ),
            ),
        ]
    source_line_start = _line_col(source, first_use.line_start)[0]
    source_line_end = max(use.source_lines[1] for use in group_uses)
    provenance = {
        "kind": "indexed-struct-pointer",
        "diagnostic": "indexed_struct_pointer_materialization",
        "variant": "direct-field-scalar-split",
        "source_lines": [source_line_start, source_line_end],
        "base_expression": first_use.base_expression,
        "index_expression": first_use.index_expression,
        "direct_expression": first_use.direct_expression,
        "field": first_use.field,
        "scalar_type": scalar_type,
        "field_uses": [
            {
                "field": use.field,
                "source_lines": list(use.source_lines),
            }
            for use in group_uses
        ],
        "split_first_field": True,
    }
    if first_use.subindex_expression is not None:
        provenance["subindex_expression"] = first_use.subindex_expression

    return LifetimeLayoutProbe(
        label=f"indexed-struct-pointer-{label_index}",
        operator="indexed-struct-pointer",
        description=(
            f"Split first direct indexed field `{first_use.expression}` into "
            f"scalar local `{temp_name}`."
        ),
        source_text=_replace_absolute_slices(source, replacements),
        provenance=provenance,
    )


def _indexed_struct_direct_field_use_is_lvalue(source: str, end: int) -> bool:
    cursor = end
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    if cursor >= len(source):
        return False
    return source.startswith(("++", "--"), cursor) or bool(
        re.match(r"(?:[+\-*/%&|^]|<<|>>)?=(?!=)", source[cursor:])
    )


def _infer_indexed_struct_direct_scalar_type(
    use: _IndexedStructDirectFieldUse,
    scoped_types: dict[str, str],
) -> str:
    initialized_type = _initialized_decl_type(use.line)
    if initialized_type is not None:
        return initialized_type

    before_use = use.line[: use.start - use.line_start]
    assign = re.search(
        r"\b(?P<lhs>[A-Za-z_]\w*)\s*(?:[+\-*/%&|^]?=|<<=|>>=)\s*$",
        before_use,
    )
    if assign is not None:
        lhs_type = scoped_types.get(assign.group("lhs"))
        if lhs_type is not None:
            return lhs_type
    return "f32"


def _unique_indexed_struct_probe_name(source: str, prefix: str) -> str:
    index = 0
    while True:
        name = f"{prefix}_{index}"
        if re.search(rf"\b{re.escape(name)}\b", source) is None:
            return name
        index += 1


def _indexed_struct_expression_is_side_effect_free(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if re.search(r"\b[A-Za-z_]\w*\s*\(", expr):
        return False
    if re.search(r"\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|,", expr):
        return False
    return True


def _indexed_struct_expression_inputs_mutated(
    region: str,
    *expressions: str | None,
) -> bool:
    names: set[str] = set()
    for expression in expressions:
        if expression is None:
            continue
        names.update(re.findall(r"\b[A-Za-z_]\w*\b", expression))
    if not names:
        return False

    code_region = _mask_c_non_code_text(region)
    for name in names:
        token = re.escape(name)
        if re.search(rf"(?:\+\+|--)\s*\b{token}\b", code_region):
            return True
        if re.search(rf"\b{token}\b\s*(?:\+\+|--)", code_region):
            return True
        if re.search(rf"(?<!&)&\s*\(*\s*\b{token}\b", code_region):
            return True
        if re.search(
            rf"\b{token}\b\s*(?:[+\-*/%&|^]=|<<=|>>=|=(?!=))",
            code_region,
        ):
            return True
    return False


def _indexed_struct_pointer_field_uses(
    source: str,
    candidate: _IndexedStructPointerCandidate,
    region_start: int,
    region_end: int,
) -> list[_IndexedStructPointerFieldUse] | None:
    region = source[region_start:region_end]
    code_region = _mask_c_non_code_text(region)
    pointer = re.escape(candidate.pointer)
    field = r"[A-Za-z_]\w*"
    use_re = re.compile(
        rf"(?P<deref>\(\s*\*\s*{pointer}\s*\)\s*\.\s*(?P<deref_field>{field}))"
        rf"|(?P<arrow>\b{pointer}\s*->\s*(?P<arrow_field>{field}))"
    )
    uses: list[_IndexedStructPointerFieldUse] = []
    excluded_ranges: list[tuple[int, int]] = []
    for match in use_re.finditer(code_region):
        start = region_start + match.start()
        end = region_start + match.end()
        if not _indexed_struct_field_use_is_standalone(code_region, match.start()):
            return None
        if _indexed_struct_field_use_is_address_taken(code_region, match.start()):
            return None
        if match.group("arrow") is not None:
            syntax = "arrow"
            field_name = match.group("arrow_field")
        else:
            syntax = "deref-dot"
            field_name = match.group("deref_field")
        if candidate.access_mode == "struct-value":
            replacement = f"{candidate.direct_expression}.{field_name}"
        else:
            replacement = f"({candidate.direct_expression})->{field_name}"
        start_line = _line_col(source, start)[0]
        end_line = _line_col(source, max(start, end - 1))[0]
        uses.append(
            _IndexedStructPointerFieldUse(
                start=start,
                end=end,
                field=field_name,
                syntax=syntax,
                replacement=replacement,
                source_lines=(start_line, end_line),
            )
        )
        excluded_ranges.append((match.start(), match.end()))

    if not uses:
        return None
    scrubbed = list(code_region)
    for start, end in excluded_ranges:
        for idx in range(start, end):
            scrubbed[idx] = " "
    if re.search(rf"\b{pointer}\b", "".join(scrubbed)):
        return None
    return uses


def _mask_c_non_code_text(text: str) -> str:
    masked = list(text)
    idx = 0

    def blank(pos: int) -> None:
        if masked[pos] != "\n":
            masked[pos] = " "

    while idx < len(text):
        char = text[idx]
        nxt = text[idx + 1] if idx + 1 < len(text) else ""
        if char == "/" and nxt == "/":
            blank(idx)
            blank(idx + 1)
            idx += 2
            while idx < len(text) and text[idx] != "\n":
                blank(idx)
                idx += 1
            continue
        if char == "/" and nxt == "*":
            blank(idx)
            blank(idx + 1)
            idx += 2
            while idx < len(text):
                end = text[idx] == "*" and idx + 1 < len(text) and text[idx + 1] == "/"
                blank(idx)
                if end:
                    blank(idx + 1)
                    idx += 2
                    break
                idx += 1
            continue
        if char in {'"', "'"}:
            quote = char
            blank(idx)
            idx += 1
            escaped = False
            while idx < len(text):
                current = text[idx]
                blank(idx)
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    idx += 1
                    break
                idx += 1
            continue
        idx += 1
    return "".join(masked)


def _indexed_struct_field_use_is_standalone(source: str, start: int) -> bool:
    cursor = start - 1
    saw_space = False
    while cursor >= 0 and source[cursor].isspace():
        saw_space = True
        cursor -= 1
    if cursor < 0:
        return True
    if saw_space:
        return source[cursor] not in ".>"
    return not (source[cursor].isalnum() or source[cursor] in "_.>")


def _indexed_struct_field_use_is_address_taken(source: str, start: int) -> bool:
    cursor = start - 1
    while cursor >= 0 and source[cursor].isspace():
        cursor -= 1
    while cursor >= 0 and source[cursor] == "(":
        cursor -= 1
        while cursor >= 0 and source[cursor].isspace():
            cursor -= 1
    if cursor < 0 or source[cursor] != "&":
        return False
    if cursor > 0 and source[cursor - 1] == "&":
        return False
    before = source[:cursor].rstrip()
    if not before:
        return True
    previous = before[-1]
    if not (previous.isalnum() or previous in "_])"):
        return True
    match = re.search(r"\b([A-Za-z_]\w*)\s*$", before)
    return bool(match and match.group(1) in {"return", "sizeof"})


def _region_has_preprocessor_directive(text: str) -> bool:
    return re.search(r"(?m)^[ \t]*#", text) is not None


def _offset_inside_preprocessor_region(
    source: str,
    region_start: int,
    offset: int,
) -> bool:
    depth = 0
    for line in source[region_start:offset].splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        directive = stripped[1:].lstrip().split(None, 1)[0] if stripped[1:] else ""
        if directive in {"if", "ifdef", "ifndef"}:
            depth += 1
        elif directive == "endif":
            depth = max(0, depth - 1)
    return depth > 0


def _probe_pointer_walk_loop(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    use = _find_pointer_walk_loop_use(source, body, body_start, function)
    if use is None:
        return []
    probes: list[LifetimeLayoutProbe] = []

    index_line = (
        use.line[:use.index_start]
        + "ll_probe_index_0"
        + use.line[use.index_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-walk-loop-index-temp-0",
            operator="pointer-walk-loop",
            description=(
                f"Name pointer-walk index expression `{use.index_expr}` before "
                f"loading `{use.base}[...]`."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                f"{use.line_indent}int ll_probe_index_0 = {use.index_expr};\n"
                f"{index_line}",
            ),
            provenance=_pointer_walk_provenance(use, "index-temp"),
        )
    )

    base_line = (
        use.line[:use.base_start]
        + "ll_probe_base_0"
        + use.line[use.base_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-walk-loop-base-alias-0",
            operator="pointer-walk-loop",
            description=(
                f"Alias pointer-walk base `{use.base}` immediately before "
                "the indexed use."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                f"{use.line_indent}{use.base_type} ll_probe_base_0 = {use.base};\n"
                f"{base_line}",
            ),
            provenance=_pointer_walk_provenance(use, "base-alias"),
        )
    )

    address_line = (
        use.line[:use.indexed_start]
        + "*ll_probe_addr_0"
        + use.line[use.indexed_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-walk-loop-address-temp-0",
            operator="pointer-walk-loop",
            description=(
                f"Name computed pointer address `{use.base} + {use.index_expr}` "
                "before the loop call."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                (
                    f"{use.line_indent}{use.base_type} ll_probe_addr_0 = "
                    f"{use.base} + {use.index_expr};\n"
                    f"{address_line}"
                ),
            ),
            provenance=_pointer_walk_provenance(use, "address-temp"),
        )
    )

    value_line = (
        use.line[:use.indexed_start]
        + "ll_probe_value_0"
        + use.line[use.indexed_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-walk-loop-value-temp-0",
            operator="pointer-walk-loop",
            description=(
                f"Name pointer-walk loaded value `{use.base}[{use.index_expr}]` "
                "before the loop call."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                (
                    f"{use.line_indent}{use.value_type} ll_probe_value_0 = "
                    f"{use.base}[{use.index_expr}];\n"
                    f"{value_line}"
                ),
            ),
            provenance=_pointer_walk_provenance(use, "value-temp"),
        )
    )

    loop_text = source[body_start + use.loop_start:body_start + use.loop_close + 1]
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-walk-loop-induction-0",
            operator="pointer-walk-loop",
            description=(
                f"Carry `{use.base}` as an induction pointer alongside "
                f"`{use.counter}`."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.loop_start,
                use.loop_close + 1,
                _pointer_walk_loop_replacement(
                    use,
                    loop_text,
                    extra_decl=f"{use.base_type} ll_probe_iter_0 = {use.base};",
                    condition=None,
                    indexed_replacement="*ll_probe_iter_0",
                ),
            ),
            provenance=_pointer_walk_provenance(use, "induction"),
        )
    )

    probes.append(
        LifetimeLayoutProbe(
            label="pointer-walk-loop-end-pointer-0",
            operator="pointer-walk-loop",
            description=(
                f"Precompute an end pointer for `{use.base}` and loop until "
                "the pointer reaches it."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.loop_start,
                use.loop_close + 1,
                _pointer_walk_loop_replacement(
                    use,
                    loop_text,
                    extra_decl=(
                        f"{use.base_type} ll_probe_iter_0 = {use.base};\n"
                        f"{use.loop_indent}    {use.base_type} ll_probe_end_0 = "
                        f"{use.base} + {use.bound};"
                    ),
                    condition="ll_probe_iter_0 < ll_probe_end_0",
                    indexed_replacement="*ll_probe_iter_0",
                ),
            ),
            provenance=_pointer_walk_provenance(use, "end-pointer"),
        )
    )

    return probes


def _pointer_walk_loop_replacement(
    use: _PointerWalkLoopUse,
    loop_text: str,
    *,
    extra_decl: str,
    condition: str | None,
    indexed_replacement: str,
) -> str:
    rel_line_start = use.line_start - use.loop_start
    rel_line_end = use.line_end - use.loop_start
    line = (
        use.line[:use.indexed_start]
        + indexed_replacement
        + use.line[use.indexed_end:]
    )
    rewritten = loop_text[:rel_line_start] + line + loop_text[rel_line_end:]
    rel_increment_end = use.increment_end - use.loop_start
    rewritten = (
        rewritten[:rel_increment_end]
        + ", ll_probe_iter_0++"
        + rewritten[rel_increment_end:]
    )
    if condition is not None:
        rel_condition_start = use.condition_start - use.loop_start
        rel_condition_end = use.condition_end - use.loop_start
        rewritten = (
            rewritten[:rel_condition_start]
            + condition
            + rewritten[rel_condition_end:]
        )
    return (
        f"{use.loop_indent}{{\n"
        f"{use.loop_indent}    {extra_decl}\n"
        f"{_indent_block_lines(rewritten, use.loop_indent)}"
        f"{use.loop_indent}}}"
    )


def _pointer_walk_provenance(
    use: _PointerWalkLoopUse,
    variant: str,
) -> dict[str, str]:
    return {
        "kind": "pointer-walk-loop",
        "variant": variant,
        "counter": use.counter,
        "base": use.base,
        "index_expr": use.index_expr,
        "bound": use.bound,
    }


def _find_pointer_walk_loop_use(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> _PointerWalkLoopUse | None:
    scoped_types = _scoped_identifier_types(source, body, body_start, function)
    loop_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)for\s*\(\s*"
        r"(?P<counter>[A-Za-z_]\w*)\s*=\s*0\s*;\s*"
        r"(?P<condition>(?P=counter)\s*<\s*(?P<bound>[^;]+?))\s*;\s*"
        r"(?P<increment>(?:(?P=counter)\+\+|\+\+(?P=counter)|"
        r"(?P=counter)\s*\+=\s*1))"
        r"\s*\)\s*\{"
    )
    for loop in loop_re.finditer(body):
        abs_open = body_start + loop.end() - 1
        abs_close = _find_matching_brace(source, abs_open)
        if abs_close is None or abs_close > body_start + len(body):
            continue
        loop_body_start = abs_open + 1
        loop_body = source[loop_body_start:abs_close]
        line_cursor = 0
        for line in loop_body.splitlines(keepends=True):
            line_start = loop_body_start - body_start + line_cursor
            line_end = line_start + len(line)
            line_cursor += len(line)
            indexed = _find_indexed_expression_in_line(
                line,
                counter=loop.group("counter"),
            )
            if indexed is None:
                continue
            base = str(indexed["base"])
            base_type = scoped_types.get(base)
            value_type = (
                _remove_pointer_from_type(base_type)
                if base_type is not None else None
            )
            if base_type is None or value_type is None:
                continue
            return _PointerWalkLoopUse(
                loop_start=loop.start(),
                loop_close=abs_close - body_start,
                loop_indent=loop.group("indent"),
                counter=loop.group("counter"),
                bound=loop.group("bound").strip(),
                bound_start=loop.start("bound"),
                bound_end=loop.end("bound"),
                condition_start=loop.start("condition"),
                condition_end=loop.end("condition"),
                increment_start=loop.start("increment"),
                increment_end=loop.end("increment"),
                line_start=line_start,
                line_end=line_end,
                line=line,
                line_indent=re.match(r"[ \t]*", line).group(0),
                base=base,
                base_start=int(indexed["base_start"]),
                base_end=int(indexed["base_end"]),
                index_expr=str(indexed["index_expr"]),
                index_start=int(indexed["index_start"]),
                index_end=int(indexed["index_end"]),
                indexed_start=int(indexed["address_start"]),
                indexed_end=int(indexed["indexed_end"]),
                base_type=base_type,
                value_type=value_type,
            )
    return None


def _probe_pointer_base_call_loop(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    use = _find_pointer_base_call_loop_use(source, body, body_start, function)
    if use is None:
        return []

    probes: list[LifetimeLayoutProbe] = []
    indexed_line = (
        use.line[:use.base_start]
        + f"{use.base}[{use.counter}]"
        + use.line[use.base_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-base-call-indexed-0",
            operator="pointer-base-call-loop",
            description=(
                f"Index pointer base `{use.base}` at `{use.counter}` at the "
                "loop call site."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                indexed_line,
            ),
            provenance=_pointer_base_call_provenance(use, "indexed"),
        )
    )

    value_line = (
        use.line[:use.base_start]
        + "ll_probe_value_0"
        + use.line[use.base_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-base-call-value-temp-0",
            operator="pointer-base-call-loop",
            description=(
                f"Name `{use.base}[{use.counter}]` before passing it to the "
                "loop call."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                (
                    f"{use.line_indent}{use.value_type} ll_probe_value_0 = "
                    f"{use.base}[{use.counter}];\n"
                    f"{value_line}"
                ),
            ),
            provenance=_pointer_base_call_provenance(use, "value-temp"),
        )
    )

    address_line = (
        use.line[:use.base_start]
        + "*ll_probe_addr_0"
        + use.line[use.base_end:]
    )
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-base-call-address-temp-0",
            operator="pointer-base-call-loop",
            description=(
                f"Name computed pointer address `{use.base} + {use.counter}` "
                "before the loop call."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.line_start,
                use.line_end,
                (
                    f"{use.line_indent}{use.base_type} ll_probe_addr_0 = "
                    f"{use.base} + {use.counter};\n"
                    f"{address_line}"
                ),
            ),
            provenance=_pointer_base_call_provenance(use, "address-temp"),
        )
    )

    loop_text = source[body_start + use.loop_start:body_start + use.loop_close + 1]
    probes.append(
        LifetimeLayoutProbe(
            label="pointer-base-call-induction-0",
            operator="pointer-base-call-loop",
            description=(
                f"Carry `{use.base}` as an induction pointer alongside "
                f"`{use.counter}` for the loop call."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.loop_start,
                use.loop_close + 1,
                _pointer_base_call_loop_replacement(
                    use,
                    loop_text,
                    extra_decl=f"{use.base_type} ll_probe_iter_0 = {use.base};",
                    condition=None,
                    base_replacement="*ll_probe_iter_0",
                ),
            ),
            provenance=_pointer_base_call_provenance(use, "induction"),
        )
    )

    probes.append(
        LifetimeLayoutProbe(
            label="pointer-base-call-end-pointer-0",
            operator="pointer-base-call-loop",
            description=(
                f"Precompute an end pointer for `{use.base}` and loop until "
                "the pointer reaches it."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                use.loop_start,
                use.loop_close + 1,
                _pointer_base_call_loop_replacement(
                    use,
                    loop_text,
                    extra_decl=(
                        f"{use.base_type} ll_probe_iter_0 = {use.base};\n"
                        f"{use.loop_indent}    {use.base_type} ll_probe_end_0 = "
                        f"{use.base} + {use.bound};"
                    ),
                    condition="ll_probe_iter_0 < ll_probe_end_0",
                    base_replacement="*ll_probe_iter_0",
                ),
            ),
            provenance=_pointer_base_call_provenance(use, "end-pointer"),
        )
    )

    return probes


def _pointer_base_call_loop_replacement(
    use: _PointerBaseCallLoopUse,
    loop_text: str,
    *,
    extra_decl: str,
    condition: str | None,
    base_replacement: str,
) -> str:
    rel_line_start = use.line_start - use.loop_start
    rel_line_end = use.line_end - use.loop_start
    line = (
        use.line[:use.base_start]
        + base_replacement
        + use.line[use.base_end:]
    )
    rewritten = loop_text[:rel_line_start] + line + loop_text[rel_line_end:]
    rel_increment_end = use.increment_end - use.loop_start
    rewritten = (
        rewritten[:rel_increment_end]
        + ", ll_probe_iter_0++"
        + rewritten[rel_increment_end:]
    )
    if condition is not None:
        rel_condition_start = use.condition_start - use.loop_start
        rel_condition_end = use.condition_end - use.loop_start
        rewritten = (
            rewritten[:rel_condition_start]
            + condition
            + rewritten[rel_condition_end:]
        )
    return (
        f"{use.loop_indent}{{\n"
        f"{use.loop_indent}    {extra_decl}\n"
        f"{_indent_block_lines(rewritten, use.loop_indent)}"
        f"{use.loop_indent}}}"
    )


def _pointer_base_call_provenance(
    use: _PointerBaseCallLoopUse,
    variant: str,
) -> dict[str, str]:
    return {
        "kind": "pointer-base-call-loop",
        "variant": variant,
        "counter": use.counter,
        "base": use.base,
        "index_expr": use.counter,
        "bound": use.bound,
    }


def _find_pointer_base_call_loop_use(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> _PointerBaseCallLoopUse | None:
    scoped_types = _scoped_identifier_types(source, body, body_start, function)
    pointer_bases = {
        name: typ for name, typ in scoped_types.items()
        if (
            (value_type := _remove_pointer_from_type(typ)) is not None
            and value_type.endswith("*")
        )
    }
    if not pointer_bases:
        return None
    loop_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)for\s*\(\s*"
        r"(?P<counter>[A-Za-z_]\w*)\s*=\s*0\s*;\s*"
        r"(?P<condition>(?P=counter)\s*<\s*(?P<bound>[^;]+?))\s*;\s*"
        r"(?P<increment>(?:(?P=counter)\+\+|\+\+(?P=counter)|"
        r"(?P=counter)\s*\+=\s*1))"
        r"\s*\)\s*\{"
    )
    for loop in loop_re.finditer(body):
        abs_open = body_start + loop.end() - 1
        abs_close = _find_matching_brace(source, abs_open)
        if abs_close is None or abs_close > body_start + len(body):
            continue
        loop_body_start = abs_open + 1
        loop_body = source[loop_body_start:abs_close]
        line_cursor = 0
        for line in loop_body.splitlines(keepends=True):
            line_start = loop_body_start - body_start + line_cursor
            line_end = line_start + len(line)
            line_cursor += len(line)
            if not re.search(rf"\b{re.escape(loop.group('counter'))}\b", line):
                continue
            for base, base_type in pointer_bases.items():
                match = re.search(rf"\b{re.escape(base)}\b", line)
                if match is None:
                    continue
                cursor = match.end()
                while cursor < len(line) and line[cursor] in " \t":
                    cursor += 1
                if cursor < len(line) and line[cursor] == "[":
                    continue
                value_type = _remove_pointer_from_type(base_type)
                if value_type is None:
                    continue
                return _PointerBaseCallLoopUse(
                    loop_start=loop.start(),
                    loop_close=abs_close - body_start,
                    loop_indent=loop.group("indent"),
                    counter=loop.group("counter"),
                    bound=loop.group("bound").strip(),
                    condition_start=loop.start("condition"),
                    condition_end=loop.end("condition"),
                    increment_end=loop.end("increment"),
                    line_start=line_start,
                    line_end=line_end,
                    line=line,
                    line_indent=re.match(r"[ \t]*", line).group(0),
                    base=base,
                    base_start=match.start(),
                    base_end=match.end(),
                    base_type=base_type,
                    value_type=value_type,
                )
    return None


def _find_indexed_pointer_loop_use(
    source: str,
    body: str,
    body_start: int,
) -> _IndexedLoopUse | None:
    loop_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)for\s*\(\s*"
        r"(?P<counter>[A-Za-z_]\w*)\s*=\s*0\s*;\s*"
        r"(?P=counter)\s*<\s*(?P<bound>[^;]+?)\s*;\s*"
        r"(?:(?P=counter)\+\+|\+\+(?P=counter)|(?P=counter)\s*\+=\s*1)"
        r"\s*\)\s*\{"
    )
    for loop in loop_re.finditer(body):
        abs_open = body_start + loop.end() - 1
        abs_close = _find_matching_brace(source, abs_open)
        if abs_close is None or abs_close > body_start + len(body):
            continue
        loop_body_start = abs_open + 1
        loop_body = source[loop_body_start:abs_close]
        line_cursor = 0
        for line in loop_body.splitlines(keepends=True):
            line_start = loop_body_start - body_start + line_cursor
            line_end = line_start + len(line)
            line_cursor += len(line)
            if _LOCAL_DECL_RE.match(line) is None:
                continue
            indexed = _find_indexed_expression_in_line(
                line,
                counter=loop.group("counter"),
            )
            if indexed is None:
                continue
            decl_type = _initialized_decl_type(line)
            return _IndexedLoopUse(
                loop_start=loop.start(),
                loop_end=loop.end(),
                loop_open=loop.end() - 1,
                loop_close=abs_close - body_start,
                loop_indent=loop.group("indent"),
                counter=loop.group("counter"),
                bound=loop.group("bound").strip(),
                bound_start=loop.start("bound"),
                bound_end=loop.end("bound"),
                line_start=line_start,
                line_end=line_end,
                line=line,
                line_indent=re.match(r"[ \t]*", line).group(0),
                base=indexed["base"],
                base_start=indexed["base_start"],
                base_end=indexed["base_end"],
                index_expr=indexed["index_expr"],
                index_start=indexed["index_start"],
                index_end=indexed["index_end"],
                address_start=indexed["address_start"],
                address_end=indexed["address_end"],
                indexed_end=indexed["indexed_end"],
                decl_type=decl_type,
            )
    return None


def _find_indexed_expression_in_line(
    line: str,
    *,
    counter: str,
) -> dict[str, object] | None:
    for match in re.finditer(r"\b(?P<base>[A-Za-z_]\w*)\s*\[", line):
        open_bracket = line.find("[", match.start())
        close_bracket = _find_matching_bracket(line, open_bracket)
        if close_bracket is None:
            continue
        index_expr = line[open_bracket + 1:close_bracket].strip()
        if not re.search(rf"\b{re.escape(counter)}\b", index_expr):
            continue
        indexed_end = close_bracket + 1
        cursor = indexed_end
        while cursor < len(line) and line[cursor] in " \t":
            cursor += 1
        if cursor < len(line) and line[cursor] == "[":
            second_close = _find_matching_bracket(line, cursor)
            if second_close is not None:
                indexed_end = second_close + 1
        return {
            "base": match.group("base"),
            "base_start": match.start("base"),
            "base_end": match.end("base"),
            "index_expr": index_expr,
            "index_start": open_bracket + 1,
            "index_end": close_bracket,
            "address_start": match.start("base"),
            "address_end": close_bracket + 1,
            "indexed_end": indexed_end,
        }
    return None


def _find_matching_bracket(text: str, open_index: int) -> int | None:
    depth = 0
    for idx in range(open_index, len(text)):
        char = text[idx]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _initialized_decl_type(line: str) -> str | None:
    match = re.match(
        r"^[ \t]*(?P<type>(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w+)(?:\s*\*)*)"
        r"\s+[A-Za-z_]\w*\s*=",
        line,
    )
    if match is None:
        return None
    return _normalize_type_spelling(match.group("type"))


def _normalize_type_spelling(type_name: str) -> str:
    type_name = type_name.replace("const ", "").replace("volatile ", "").strip()
    return re.sub(r"\s*\*\s*", "*", type_name)


def _add_pointer_to_type(type_name: str) -> str:
    return _normalize_type_spelling(type_name) + "*"


def _remove_pointer_from_type(type_name: str) -> str | None:
    normalized = _normalize_type_spelling(type_name)
    if not normalized.endswith("*"):
        return None
    return normalized[:-1]


def _probe_nested_loop_counter_hoist(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> tuple[LifetimeLayoutProbe | None, LifetimeLayoutProbe | None]:
    decls = _iter_decl_lines(body)
    top_decls = [decl for decl in decls if decl.depth == 0]
    if not top_decls:
        return None, None

    for decl in decls:
        if decl.depth == 0 or decl.type_name not in {"int", "s32"}:
            continue
        loop_start = _find_loop_using_counter(body, decl.end, decl.name)
        if loop_start is None:
            continue
        between = body[decl.end:loop_start]
        if between.strip():
            continue

        insert_type = "int"
        existing_top_counter = next(
            (
                top_decl
                for top_decl in top_decls
                if top_decl.name == decl.name and top_decl.type_name == insert_type
            ),
            None,
        )
        if existing_top_counter is not None:
            reused_source = _replace_body_slice(
                source,
                body_start,
                decl.start,
                decl.end,
                "",
            )
            reused_probe = LifetimeLayoutProbe(
                label="loop-counter-hoist-before-0",
                operator="loop-counter-hoist",
                description=(
                    f"Reuse existing function-scope loop counter `{decl.name}` "
                    f"and remove nested {decl.type_name} declaration."
                ),
                source_text=reused_source,
                provenance={
                    "kind": "loop-counter-hoist",
                    "counter": decl.name,
                    "from_type": decl.type_name,
                    "to_type": insert_type,
                    "placement": "reuse:function-scope",
                },
            )
            return reused_probe, None

        insert_indent = top_decls[0].indent
        insert_text = f"{insert_indent}{insert_type} {decl.name};\n"

        before_target = _preferred_loop_counter_insert_target(top_decls)
        before_source = _move_decl_to_body_offset(
            source,
            body,
            body_start,
            decl,
            before_target.start,
            insert_text,
        )
        before_probe = LifetimeLayoutProbe(
            label="loop-counter-hoist-before-0",
            operator="loop-counter-hoist",
            description=(
                f"Hoist nested loop counter `{decl.name}` to function scope "
                f"before `{before_target.name}` as int."
            ),
            source_text=before_source,
            provenance={
                "kind": "loop-counter-hoist",
                "counter": decl.name,
                "from_type": decl.type_name,
                "to_type": insert_type,
                "placement": f"before:{before_target.name}",
            },
        )

        after_probe: LifetimeLayoutProbe | None = None
        if len(top_decls) > 1:
            after_source = _move_decl_to_body_offset(
                source,
                body,
                body_start,
                decl,
                before_target.end,
                insert_text,
            )
            after_probe = LifetimeLayoutProbe(
                label="loop-counter-hoist-after-0",
                operator="loop-counter-hoist",
                description=(
                    f"Hoist nested loop counter `{decl.name}` immediately "
                    f"after `{before_target.name}` as int."
                ),
                source_text=after_source,
                provenance={
                    "kind": "loop-counter-hoist",
                    "counter": decl.name,
                    "from_type": decl.type_name,
                    "to_type": insert_type,
                    "placement": f"after:{before_target.name}",
                },
            )
        return before_probe, after_probe

    return None, None


def _probe_sibling_loop_counter_hoists(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    decls = _iter_decl_lines(body)
    top_decls = [decl for decl in decls if decl.depth == 0]
    if not top_decls:
        return []

    loops: list[_SiblingCounterLoop] = []
    for decl in decls:
        if decl.depth == 0 or decl.type_name not in {"int", "s32"}:
            continue
        use = _sibling_counter_loop_for_decl(source, body, body_start, decl)
        if use is not None:
            loops.append(use)

    grouped: dict[tuple[str, str, str, int], list[_SiblingCounterLoop]] = {}
    for use in loops:
        key = (use.decl.name, use.shape, use.call_symbol, use.decl.depth)
        grouped.setdefault(key, []).append(use)

    probes: list[LifetimeLayoutProbe] = []
    for (counter, _shape, call_symbol, _depth), group in grouped.items():
        safe = [use for use in group if not use.indexed_by_counter]
        if len(safe) < 2:
            continue
        selected = safe[:2]
        existing_top_counter = next(
            (
                decl
                for decl in top_decls
                if decl.name == counter and decl.type_name == "int"
            ),
            None,
        )
        conflicting_top_counter = next(
            (
                decl
                for decl in top_decls
                if decl.name == counter and decl.type_name != "int"
            ),
            None,
        )
        if existing_top_counter is not None:
            insert_offset = existing_top_counter.start
            insert_text = ""
            placement = "reuse:function-scope"
        elif conflicting_top_counter is not None:
            continue
        else:
            before_target = _preferred_loop_counter_insert_target(top_decls)
            insert_offset = before_target.start
            insert_text = f"{before_target.indent}int {counter};\n"
            placement = "function-scope"

        selected_decls = [use.decl for use in selected]
        mutated_body = _remove_decls_and_insert_text(
            body,
            selected_decls,
            insert_offset,
            insert_text,
        )
        probes.append(
            LifetimeLayoutProbe(
                label=f"sibling-loop-counter-hoist-function-{len(probes)}",
                operator="loop-counter-hoist",
                description=(
                    f"Hoist loop counter `{counter}` for {len(selected)} "
                    f"sibling `{call_symbol}` call loops while leaving indexed "
                    "loops block-local."
                ),
                source_text=(
                    source[:body_start]
                    + mutated_body
                    + source[body_start + len(body):]
                ),
                provenance={
                    "kind": "sibling-loop-counter-hoist",
                    "counter": counter,
                    "call_symbol": call_symbol,
                    "loop_count": len(selected),
                    "placement": placement,
                    "skipped_indexed_loops": sum(
                        1 for use in group if use.indexed_by_counter
                    ),
                },
            )
        )
        break
    return probes


def _sibling_counter_loop_for_decl(
    source: str,
    body: str,
    body_start: int,
    decl: _DeclLine,
) -> _SiblingCounterLoop | None:
    loop_start = _find_loop_using_counter(body, decl.end, decl.name)
    if loop_start is None:
        return None
    if body[decl.end:loop_start].strip():
        return None

    counter = re.escape(decl.name)
    loop_re = re.compile(
        rf"[ \t]*for\s*\(\s*{counter}\s*=\s*(?P<init>[^;]+);\s*"
        rf"{counter}\s*<\s*(?P<bound>[^;]+);\s*"
        rf"(?:{counter}\s*\+\+|\+\+\s*{counter})\s*\)\s*\{{",
        re.MULTILINE,
    )
    match = loop_re.match(body, loop_start)
    if match is None:
        return None

    loop_open = match.end() - 1
    loop_close_abs = _find_matching_brace(source, body_start + loop_open)
    if loop_close_abs is None:
        return None
    loop_close = loop_close_abs - body_start
    if loop_close > len(body):
        return None

    loop_body = body[loop_open + 1:loop_close]
    call_symbol = _first_counter_call_symbol(loop_body, decl.name)
    if call_symbol is None:
        return None
    return _SiblingCounterLoop(
        decl=decl,
        loop_start=loop_start,
        loop_close=loop_close,
        shape=(
            f"init={_normalize_loop_shape_expr(match.group('init'))};"
            f"bound={_normalize_loop_shape_expr(match.group('bound'))};"
            "inc=++"
        ),
        call_symbol=call_symbol,
        indexed_by_counter=_loop_indexes_with_counter(loop_body, decl.name),
    )


def _first_counter_call_symbol(loop_body: str, counter: str) -> str | None:
    call_re = re.compile(
        r"\b(?P<call>[A-Za-z_]\w*)\s*\((?P<args>[^;{}]*)\)\s*;"
    )
    for match in call_re.finditer(loop_body):
        if re.search(rf"\b{re.escape(counter)}\b", match.group("args")):
            return match.group("call")
    return None


def _loop_indexes_with_counter(loop_body: str, counter: str) -> bool:
    return (
        re.search(
            rf"\[[^\]\n;]*\b{re.escape(counter)}\b[^\]\n;]*\]",
            loop_body,
        )
        is not None
    )


def _normalize_loop_shape_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr.strip())


def _remove_decls_and_insert_text(
    body: str,
    decls: list[_DeclLine],
    insert_offset: int,
    insert_text: str,
) -> str:
    mutated = body
    adjusted_insert = insert_offset
    for decl in sorted(decls, key=lambda item: item.start, reverse=True):
        mutated = mutated[:decl.start] + mutated[decl.end:]
        if decl.start < adjusted_insert:
            adjusted_insert -= decl.end - decl.start
    if insert_text:
        mutated = (
            mutated[:adjusted_insert]
            + insert_text
            + mutated[adjusted_insert:]
        )
    return mutated


def _preferred_loop_counter_insert_target(decls: list[_DeclLine]) -> _DeclLine:
    count_decl = next((decl for decl in decls if decl.name == "count"), None)
    return count_decl or decls[0]


def _move_decl_to_body_offset(
    source: str,
    body: str,
    body_start: int,
    decl: _DeclLine,
    insert_offset: int,
    insert_text: str,
) -> str:
    body_without_decl = body[:decl.start] + body[decl.end:]
    adjusted_insert = insert_offset
    if insert_offset > decl.start:
        adjusted_insert -= decl.end - decl.start
    moved_body = (
        body_without_decl[:adjusted_insert]
        + insert_text
        + body_without_decl[adjusted_insert:]
    )
    return source[:body_start] + moved_body + source[body_start + len(body):]


def _find_loop_using_counter(body: str, start: int, name: str) -> int | None:
    match = re.search(
        rf"(?m)^([ \t]*)for\s*\(\s*{re.escape(name)}\s*=",
        body[start:],
    )
    if match is None:
        return None
    return start + match.start()


def _probe_assignment_expression_cse_removal(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    assign_re = re.compile(
        rf"\(\s*(?P<temp>[A-Za-z_]\w*)\s*=\s*(?P<expr>{_MEMBER_EXPR_RE})\s*\)"
    )
    for match in assign_re.finditer(body):
        temp = match.group("temp")
        expr = _normalize_inline_expr(match.group("expr"))
        stmt_start, stmt_end = _statement_bounds_around(body, match.start())
        if stmt_start is None or stmt_end is None:
            continue
        statement = body[stmt_start:stmt_end]
        rel_start = match.start() - stmt_start
        rel_end = match.end() - stmt_start
        rewritten = statement[:rel_start] + expr + statement[rel_end:]
        replace_from = rel_start + len(expr)
        rewritten = (
            rewritten[:replace_from]
            + re.sub(
                rf"\b{re.escape(temp)}\b",
                expr,
                rewritten[replace_from:],
            )
        )
        if rewritten == statement:
            continue
        return LifetimeLayoutProbe(
            label="assignment-expression-cse-removal-0",
            operator="expression-shape",
            description=(
                f"Remove assignment-in-expression temp `{temp}` and repeat "
                "the natural operand expression."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                stmt_start,
                stmt_end,
                rewritten,
            ),
            provenance={
                "kind": "assignment-expression-cse-removal",
                "temp": temp,
                "expr": expr,
            },
        )
    return None


def _probe_distance_component_temps(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    component_re = re.compile(
        rf"\(\s*\((?P<dx>{_DIFF_EXPR_RE})\)\s*\*\s*\((?P=dx)\)\s*\)"
        rf"\s*\+\s*"
        rf"\(\s*\((?P<dy>{_DIFF_EXPR_RE})\)\s*\*\s*\((?P=dy)\)\s*\)",
        re.MULTILINE,
    )
    for match in component_re.finditer(body):
        stmt_start, stmt_end = _statement_bounds_around(body, match.start())
        if stmt_start is None or stmt_end is None:
            continue
        stmt_line_end = body.find("\n", stmt_start)
        if stmt_line_end < 0 or stmt_line_end > stmt_end:
            stmt_line_end = stmt_end
        indent_match = re.match(r"[ \t]*", body[stmt_start:stmt_line_end])
        indent = indent_match.group(0) if indent_match else ""
        dx = _normalize_inline_expr(match.group("dx"))
        dy = _normalize_inline_expr(match.group("dy"))
        replacement = (
            "(ll_probe_dx_0 * ll_probe_dx_0) + "
            "(ll_probe_dy_0 * ll_probe_dy_0)"
        )
        statement = body[stmt_start:stmt_end]
        rel_start = match.start() - stmt_start
        rel_end = match.end() - stmt_start
        insertion = (
            f"{indent}float ll_probe_dx_0 = {dx};\n"
            f"{indent}float ll_probe_dy_0 = {dy};\n"
        )
        rewritten = statement[:rel_start] + replacement + statement[rel_end:]
        return LifetimeLayoutProbe(
            label="distance-component-temps-0",
            operator="expression-shape",
            description="Introduce named dx/dy temps for a repeated squared-distance expression.",
            source_text=_replace_body_slice(
                source,
                body_start,
                stmt_start,
                stmt_end,
                insertion + rewritten,
            ),
            provenance={
                "kind": "distance-component-temps",
                "dx": dx,
                "dy": dy,
            },
        )
    return None


def _probe_abs_branch_discriminator_split(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    expr = rf"(?P<expr>{_DIFF_EXPR_RE})"
    patterns = [
        re.compile(
            rf"(?m)^([ \t]*)(?P<type>float|f32|double)\s+"
            rf"(?P<name>[A-Za-z_]\w*)\s*=\s*{expr}\s*;\n?"
        ),
        re.compile(
            rf"(?m)^([ \t]*)(?P<name>[A-Za-z_]\w*)\s*=\s*{expr}\s*;\n?"
        ),
    ]
    for assign_re in patterns:
        for assign in assign_re.finditer(body):
            indent = assign.group(1)
            value_name = assign.group("name")
            branch_re = re.compile(
                rf"(?m)^([ \t]*)if\s*\(\s*{re.escape(value_name)}\s*>\s*"
                r"0(?:\.0f?)?\s*\)\s*\{"
            )
            branch = branch_re.search(body, assign.end())
            if branch is None:
                continue
            branch_open = body_start + branch.end() - 1
            branch_close = _find_matching_brace(source, branch_open)
            if branch_close is None or branch_close > body_start + len(body):
                continue
            branch_body = source[branch_open + 1:branch_close]
            if not re.search(
                rf"\bif\s*\(\s*{re.escape(value_name)}\s*<\s*0(?:\.0f?)?\s*\)",
                branch_body,
            ):
                continue

            temp = "ll_probe_abs_discriminator_0"
            expression = _normalize_inline_expr(assign.group("expr"))
            if "type" in assign.groupdict() and assign.group("type"):
                type_name = assign.group("type")
                replacement = (
                    f"{indent}{type_name} {temp} = {expression};\n"
                    f"{indent}{type_name} {value_name} = {temp};\n"
                )
            else:
                replacement = (
                    f"{indent}float {temp};\n"
                    f"{indent}{temp} = {expression};\n"
                    f"{indent}{value_name} = {temp};\n"
                )
            branch_header_start = body_start + branch.start()
            branch_header_end = body_start + branch.end()
            branch_header = source[branch_header_start:branch_header_end]
            rewritten_header = re.sub(
                rf"\b{re.escape(value_name)}\b",
                temp,
                branch_header,
                count=1,
            )
            mutated = _replace_absolute_slice(
                source,
                branch_header_start,
                branch_header_end,
                rewritten_header,
            )
            mutated = _replace_body_slice(
                mutated,
                body_start,
                assign.start(),
                assign.end(),
                replacement,
            )
            return LifetimeLayoutProbe(
                label="abs-branch-discriminator-split-0",
                operator="expression-shape",
                description=(
                    f"Split `{value_name}` branch discriminator from the abs "
                    "materialization local."
                ),
                source_text=mutated,
                provenance={
                    "kind": "abs-branch-discriminator-split",
                    "value_local": value_name,
                    "discriminator_local": temp,
                    "expression": expression,
                },
            )
    return None


def _probe_boolean_guard_switch(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    if re.search(rf"\bvoid\s+{re.escape(function)}\s*\(", source[:body_start]) is None:
        return None
    for match in re.finditer(r"(?m)^([ \t]*)if\s*\(", body):
        indent = match.group(1)
        condition_start = body_start + match.end() - 1
        condition_end = _find_matching_paren(source, condition_start)
        if condition_end is None or condition_end > body_end:
            continue
        condition = source[condition_start + 1:condition_end].strip()
        if not re.fullmatch(r"[A-Za-z_]\w*\s*\([^{};]*\)", condition):
            continue
        open_brace = source.find("{", condition_end, body_end)
        if open_brace < 0:
            continue
        close_brace = _find_matching_brace(source, open_brace)
        if close_brace is None or close_brace > body_end:
            continue
        if not re.fullmatch(r"\s*return\s*;\s*", source[open_brace + 1:close_brace]):
            continue
        trailing = source[close_brace + 1:body_end].lstrip()
        if trailing.startswith("else"):
            continue
        replacement = (
            f"{indent}switch ({condition}) {{\n"
            f"{indent}case 0:\n"
            f"{indent}    break;\n"
            f"{indent}default:\n"
            f"{indent}    return;\n"
            f"{indent}}}"
        )
        return LifetimeLayoutProbe(
            label="boolean-guard-switch-0",
            operator="guard-shape",
            description=(
                "Rewrite a boolean call guard return as case 0/default switch."
            ),
            source_text=_replace_absolute_slice(
                source,
                body_start + match.start(),
                close_brace + 1,
                replacement,
            ),
            provenance={
                "kind": "boolean-guard-switch",
                "condition": condition,
            },
        )
    return None


def _statement_bounds_around(
    text: str,
    offset: int,
) -> tuple[int | None, int | None]:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find(";", offset)
    if end < 0:
        return None, None
    return start, end + 1


def _normalize_inline_expr(expr: str) -> str:
    return re.sub(r"\s+", " ", expr).replace(" -> ", "->").replace(" . ", ".").strip()


@dataclass(frozen=True)
class _CallReturnCompareChain:
    result_var: str
    compare_var: str
    call_symbol: str
    call_expression: str
    call_line_start: int
    call_expr_start: int
    copy_start: int
    copy_end: int
    first_value: str
    second_value: str
    first_if_start: int
    first_open: int
    first_close: int
    else_start: int
    else_open: int
    else_close: int
    second_if_start: int
    second_open: int
    second_close: int
    indent: str
    inner_indent: str


def _probe_call_return_compare_chain(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    chain = _find_call_return_compare_chain(source, body, body_start, body_end)
    if chain is None:
        return []
    first_body = source[chain.first_open + 1:chain.first_close]
    second_body = source[chain.second_open + 1:chain.second_close]
    original_start = chain.copy_start
    original_end = chain.else_close + 1
    provenance = _call_return_compare_provenance(source, chain)
    probes = [
        LifetimeLayoutProbe(
            label="call-return-compare-switch-0",
            operator="call-return-compare-chain",
            description=(
                f"Rewrite `{chain.compare_var}` call-result compares as a switch."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_call_return_switch(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
        LifetimeLayoutProbe(
            label="call-return-compare-inverted-0",
            operator="call-return-compare-chain",
            description=(
                f"Try the `{chain.second_value}` compare before "
                f"`{chain.first_value}`."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_inverted_compare_chain(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
        LifetimeLayoutProbe(
            label="call-return-compare-copy-in-else-0",
            operator="call-return-compare-chain",
            description=(
                f"Compare `{chain.result_var}` first and copy into "
                f"`{chain.compare_var}` only in the else arm."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_copy_in_else_chain(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
        LifetimeLayoutProbe(
            label="call-return-compare-split-direct-0",
            operator="call-return-compare-chain",
            description=(
                f"Use `{chain.result_var}` for the first compare, then copy "
                f"for the second compare after the first branch."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_split_direct_chain(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
    ]
    pointer_probe = _probe_call_return_narrow_pointer(source, chain, provenance)
    if pointer_probe is not None:
        probes.append(pointer_probe)
    return probes


def _find_call_return_compare_chain(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
) -> _CallReturnCompareChain | None:
    assign_re = re.compile(
        r"(?m)^([ \t]*)(?P<result>[A-Za-z_]\w*)\s*=\s*"
        r"(?P<expr>(?P<call>[A-Za-z_]\w*)\s*\([^;\n]*\))\s*;\n"
    )
    for assign in assign_re.finditer(body):
        result_var = assign.group("result")
        rel = assign.end()
        copy_re = re.compile(
            rf"(?m)^([ \t]*)(?P<compare>[A-Za-z_]\w*)\s*=\s*"
            rf"{re.escape(result_var)}\s*;\n"
        )
        copy = copy_re.match(body, rel)
        if copy is None:
            continue
        compare_var = copy.group("compare")
        indent = copy.group(1)
        first_re = re.compile(
            rf"\s*if\s*\(\s*{re.escape(compare_var)}\s*==\s*"
            rf"(?P<value>-?\d+)\s*\)\s*\{{",
            re.MULTILINE,
        )
        first = first_re.match(body, copy.end())
        if first is None:
            continue
        first_open = body_start + first.end() - 1
        first_close = _find_matching_brace(source, first_open)
        if first_close is None or first_close > body_end:
            continue
        else_match = re.match(
            r"\s*else\s*\{",
            source[first_close + 1:body_end],
        )
        if else_match is None:
            continue
        else_start = first_close + 1 + else_match.start()
        else_open = first_close + 1 + else_match.end() - 1
        else_close = _find_matching_brace(source, else_open)
        if else_close is None or else_close > body_end:
            continue
        second_re = re.compile(
            rf"\s*if\s*\(\s*{re.escape(compare_var)}\s*==\s*"
            rf"(?P<value>-?\d+)\s*\)\s*\{{",
            re.MULTILINE,
        )
        second = second_re.match(source, else_open + 1, else_close)
        if second is None:
            continue
        second_open = second.end() - 1
        second_close = _find_matching_brace(source, second_open)
        if second_close is None or second_close > else_close:
            continue
        return _CallReturnCompareChain(
            result_var=result_var,
            compare_var=compare_var,
            call_symbol=assign.group("call"),
            call_expression=assign.group("expr").strip(),
            call_line_start=body_start + assign.start(),
            call_expr_start=body_start + assign.start("expr"),
            copy_start=body_start + copy.start(),
            copy_end=body_start + copy.end(),
            first_value=first.group("value"),
            second_value=second.group("value"),
            first_if_start=body_start + first.start(),
            first_open=first_open,
            first_close=first_close,
            else_start=else_start,
            else_open=else_open,
            else_close=else_close,
            second_if_start=second.start(),
            second_open=second_open,
            second_close=second_close,
            indent=indent,
            inner_indent=indent + "    ",
        )
    return None


def _call_return_compare_provenance(
    source: str,
    chain: _CallReturnCompareChain,
) -> dict:
    line, col = _line_col(source, chain.call_expr_start)
    return {
        "kind": "call-return-compare-chain",
        "call_symbol": chain.call_symbol,
        "call_expression": chain.call_expression,
        "result_var": chain.result_var,
        "compare_var": chain.compare_var,
        "compare_values": [int(chain.first_value), int(chain.second_value)],
        "source_line": line,
        "source_col": col,
    }


def _render_call_return_switch(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.indent}switch ({chain.compare_var}) {{\n"
        f"{chain.indent}case {chain.first_value}: {{"
        f"{first_body}"
        f"{chain.inner_indent}break;\n"
        f"{chain.indent}}}\n"
        f"{chain.indent}case {chain.second_value}: {{"
        f"{second_body}"
        f"{chain.inner_indent}break;\n"
        f"{chain.indent}}}\n"
        f"{chain.indent}}}"
    )


def _render_inverted_compare_chain(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.indent}if ({chain.compare_var} == {chain.second_value}) {{"
        f"{second_body}"
        f"{chain.indent}}} else {{\n"
        f"{chain.inner_indent}if ({chain.compare_var} == {chain.first_value}) {{"
        f"{_indent_block_lines(first_body, chain.inner_indent)}"
        f"{chain.inner_indent}}}\n"
        f"{chain.indent}}}"
    )


def _render_copy_in_else_chain(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}if ({chain.result_var} == {chain.first_value}) {{"
        f"{first_body}"
        f"{chain.indent}}} else {{\n"
        f"{chain.inner_indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.inner_indent}if ({chain.compare_var} == {chain.second_value}) {{"
        f"{_indent_block_lines(second_body, chain.inner_indent)}"
        f"{chain.inner_indent}}}\n"
        f"{chain.indent}}}"
    )


def _render_split_direct_chain(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}if ({chain.result_var} == {chain.first_value}) {{"
        f"{first_body}"
        f"{chain.indent}}}\n"
        f"{chain.indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.indent}if ({chain.compare_var} == {chain.second_value}) {{"
        f"{second_body}"
        f"{chain.indent}}}"
    )


def _probe_call_return_narrow_pointer(
    source: str,
    chain: _CallReturnCompareChain,
    provenance: dict,
) -> LifetimeLayoutProbe | None:
    first_body = source[chain.first_open + 1:chain.first_close]
    body_offset = chain.first_open + 1
    pointer_re = re.compile(
        r"(?m)^([ \t]*)(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
        r"(?:\s*\*)+\s+([A-Za-z_]\w*)\s*=\s*[^;\n]+;\n"
    )
    for match in pointer_re.finditer(first_body):
        indent, name = match.groups()
        rel_start = match.start()
        abs_start = body_offset + rel_start
        rel_use_end = _last_line_end_for_identifiers(
            first_body,
            rel_start,
            (name,),
        )
        if rel_use_end is None:
            continue
        abs_use_end = body_offset + _balanced_region_end(
            first_body,
            rel_start,
            rel_use_end,
        )
        region = source[abs_start:abs_use_end]
        wrapped = _wrap_block_text(region, indent)
        return LifetimeLayoutProbe(
            label="call-return-compare-narrow-pointer-0",
            operator="call-return-compare-chain",
            description=(
                f"Narrow dependent pointer `{name}` inside the "
                f"`{chain.compare_var} == {chain.first_value}` branch."
            ),
            source_text=_replace_absolute_slice(source, abs_start, abs_use_end, wrapped),
            provenance={**provenance, "dependent_pointer": name},
        )
    return None


def _replace_absolute_slice(
    source: str,
    start: int,
    end: int,
    replacement: str,
) -> str:
    return source[:start] + replacement + source[end:]


def _line_col(source: str, offset: int) -> tuple[int, int]:
    line = source.count("\n", 0, offset) + 1
    last_newline = source.rfind("\n", 0, offset)
    col = offset + 1 if last_newline < 0 else offset - last_newline
    return line, col


def _leading_local_decl_names(text: str) -> tuple[str, ...]:
    names: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if names:
                continue
            break
        match = _LOCAL_DECL_RE.match(line)
        if match is None:
            break
        names.append(match.group(1))
    return tuple(names)


def _last_line_end_for_identifiers(
    text: str,
    start: int,
    names: tuple[str, ...],
) -> int | None:
    token_re = re.compile(
        r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b"
    )
    last_end: int | None = None
    cursor = start
    for line in text[start:].splitlines(keepends=True):
        line_end = cursor + len(line)
        if token_re.search(line):
            last_end = line_end
        cursor = line_end
    return last_end


def _first_later_line_with_identifier(
    text: str,
    start: int,
    name: str,
) -> int | None:
    token_re = re.compile(r"\b" + re.escape(name) + r"\b")
    cursor = start
    for line in text[start:].splitlines(keepends=True):
        stripped = line.strip()
        if stripped and token_re.search(line):
            return cursor
        cursor += len(line)
    return None


def _paragraph_end(text: str, start: int) -> int:
    cursor = start
    saw_content = False
    for line in text[start:].splitlines(keepends=True):
        if saw_content and not line.strip():
            return cursor
        if line.strip():
            saw_content = True
        cursor += len(line)
    return len(text)


def _block_crosses_shallower_else(block: str, first_line: str) -> bool:
    first_indent_len = len(first_line) - len(first_line.lstrip(" \t"))
    for line in block.splitlines():
        stripped = line.lstrip(" \t")
        if not stripped.startswith("} else"):
            continue
        else_indent_len = len(line) - len(stripped)
        if else_indent_len < first_indent_len:
            return True
    return False


def _declaration_use_region_end(text: str, start: int, name: str) -> int | None:
    last_use_end = _last_line_end_for_identifiers(text, start, (name,))
    if last_use_end is None:
        return None
    return _balanced_region_end(text, start, last_use_end)


def _balanced_region_end(text: str, start: int, min_end: int) -> int:
    cursor = start
    depth = 0
    for line in text[start:].splitlines(keepends=True):
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
        cursor += len(line)
        if cursor >= min_end and depth == 0:
            return cursor
    return len(text)


def _wrap_block_text(text: str, indent: str) -> str:
    inner = _indent_block_lines(text, indent)
    if not inner.endswith("\n"):
        inner += "\n"
    return f"{indent}{{\n{inner}{indent}}}\n"


def _indent_block_lines(text: str, indent: str) -> str:
    inner_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if not line.strip():
            inner_lines.append(line)
        elif line.startswith(indent):
            inner_lines.append(f"{indent}    {line[len(indent):]}")
        else:
            inner_lines.append(f"{indent}    {line}")
    return "".join(inner_lines)


def _outdent_block_lines(text: str, from_indent: str, to_indent: str) -> str:
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith(from_indent):
            lines.append(to_indent + line[len(from_indent):])
        else:
            lines.append(line)
    return "".join(lines)


def _split_top_level_args(args_text: str) -> tuple[str, ...]:
    args: list[str] = []
    start = 0
    depth = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for idx, char in enumerate(args_text):
        if char in pairs:
            depth += 1
        elif char in closing and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            args.append(args_text[start:idx].strip())
            start = idx + 1
    tail = args_text[start:].strip()
    if tail:
        args.append(tail)
    return tuple(args)


def _has_tempizable_arithmetic(expr: str) -> bool:
    expr = expr.strip().replace("->", "")
    return (
        "+" in expr
        or "*" in expr
        or "/" in expr
        or re.search(r"[\w\]\)]\s*-\s*(?:[A-Za-z_]\w*|\d|\()", expr)
        is not None
    )


def _find_matching_brace(source: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _find_matching_paren(source: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(source)):
        char = source[idx]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return idx
    return None
