"""Suggest C source reshapes from divergent scheduler-window decisions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .schedule_explain import (
    ScheduleCandidate,
    ScheduleDiffFinding,
    diff_schedule,
)


@dataclass(frozen=True)
class ScheduleSourceSuggestion:
    rank: int
    kind: str
    title: str
    mechanically_applicable: bool
    target_expression: str | None
    observed_expression: str | None
    source_file: str | None
    source_line: int | None
    source_col: int | None
    patch_hint: str
    rationale: str


@dataclass(frozen=True)
class ScheduleSuggestReport:
    function: str
    mode: str
    caveat: str
    finding: ScheduleDiffFinding | None
    suggestions: tuple[ScheduleSourceSuggestion, ...]


def _candidate_expression(cand: ScheduleCandidate | None) -> str | None:
    if cand is None:
        return None
    if cand.source is not None and cand.source.expression:
        return cand.source.expression
    if cand.source is not None and cand.source.base_var and cand.source.field_offset is not None:
        return f"{cand.source.base_var}->x{cand.source.field_offset:X}"
    if cand.offset is not None and cand.base:
        return f"{cand.opcode} 0x{cand.offset:X}({cand.base})"
    return None


def _source_location(
    *candidates: ScheduleCandidate | None,
) -> tuple[str | None, int | None, int | None]:
    for cand in candidates:
        if cand is None or cand.source is None:
            continue
        if cand.source.source_file and cand.source.source_line is not None:
            return (
                cand.source.source_file,
                cand.source.source_line,
                cand.source.source_col,
            )
    return None, None, None


def _same_source_line(
    lhs: ScheduleCandidate | None,
    rhs: ScheduleCandidate | None,
) -> bool:
    if lhs is None or rhs is None or lhs.source is None or rhs.source is None:
        return False
    return (
        lhs.source.source_file is not None
        and lhs.source.source_file == rhs.source.source_file
        and lhs.source.source_line is not None
        and lhs.source.source_line == rhs.source.source_line
    )


def _same_base(lhs: ScheduleCandidate | None, rhs: ScheduleCandidate | None) -> bool:
    if lhs is None or rhs is None:
        return False
    lhs_base = lhs.source.base_var if lhs.source is not None else lhs.base
    rhs_base = rhs.source.base_var if rhs.source is not None else rhs.base
    return lhs_base is not None and lhs_base == rhs_base


def _build_suggestions(finding: ScheduleDiffFinding) -> tuple[ScheduleSourceSuggestion, ...]:
    real = finding.real_pick
    forced = finding.forced_pick
    observed_expr = _candidate_expression(real)
    target_expr = _candidate_expression(forced)
    source_file, source_line, source_col = _source_location(forced, real)
    has_expressions = observed_expr is not None and target_expr is not None
    same_line = _same_source_line(real, forced)
    same_base = _same_base(real, forced)

    suggestions: list[ScheduleSourceSuggestion] = []
    suggestions.append(ScheduleSourceSuggestion(
        rank=1,
        kind="split-enclosing-statement",
        title="Split the enclosing statement or call into ordered temporaries",
        mechanically_applicable=has_expressions and source_line is not None,
        target_expression=target_expr,
        observed_expression=observed_expr,
        source_file=source_file,
        source_line=source_line,
        source_col=source_col,
        patch_hint=(
            f"Evaluate `{target_expr}` into a temp immediately before "
            f"`{observed_expr}`, then pass/use the temps in the original "
            "statement."
            if has_expressions
            else "Split the enclosing statement around the forced-picked load first."
        ),
        rationale=(
            "The forced path picked this load first at the divergent scheduler "
            "window; splitting the source gives MWCC a concrete evaluation-order "
            "shape to try instead of relying on argument/subexpression order."
        ),
    ))

    if has_expressions:
        suggestions.append(ScheduleSourceSuggestion(
            rank=2,
            kind="reorder-source-reads",
            title="Reorder the adjacent field reads in source order",
            mechanically_applicable=same_line,
            target_expression=target_expr,
            observed_expression=observed_expr,
            source_file=source_file,
            source_line=source_line,
            source_col=source_col,
            patch_hint=(
                f"Move `{target_expr}` before `{observed_expr}` within the "
                "same call, initializer, or expression tree."
            ),
            rationale=(
                "This is the smallest source-order probe when both field reads "
                "come from the same statement, but treat it as a probe because "
                "MWCC scheduler priority data is unavailable."
            ),
        ))

        suggestions.append(ScheduleSourceSuggestion(
            rank=3,
            kind="introduce-load-temporary",
            title="Materialize one field read through a named temporary",
            mechanically_applicable=True,
            target_expression=target_expr,
            observed_expression=observed_expr,
            source_file=source_file,
            source_line=source_line,
            source_col=source_col,
            patch_hint=(
                f"Introduce a local temp for `{target_expr}` before the "
                f"statement that also reads `{observed_expr}`."
            ),
            rationale=(
                "A named temporary can separate the load from a larger "
                "expression tree and change where MWCC exposes it to the "
                "scheduler."
            ),
        ))

    if same_base and has_expressions:
        suggestions.append(ScheduleSourceSuggestion(
            rank=4,
            kind="separate-base-pointer",
            title="Separate the shared base pointer before the field reads",
            mechanically_applicable=True,
            target_expression=target_expr,
            observed_expression=observed_expr,
            source_file=source_file,
            source_line=source_line,
            source_col=source_col,
            patch_hint=(
                "Assign the shared object/global pointer to a local pointer, "
                f"then read `{target_expr}` and `{observed_expr}` through that "
                "local in the desired order."
            ),
            rationale=(
                "When both loads share a base, changing the source's base "
                "materialization can alter the nearby load graph without "
                "changing program semantics."
            ),
        ))

    real_field = real.source.field_name if real and real.source else None
    forced_field = forced.source.field_name if forced and forced.source else None
    if has_expressions and real_field and forced_field:
        suggestions.append(ScheduleSourceSuggestion(
            rank=5,
            kind="reorder-file-local-fields",
            title="Try a file-local struct field declaration order probe",
            mechanically_applicable=False,
            target_expression=target_expr,
            observed_expression=observed_expr,
            source_file=source_file,
            source_line=source_line,
            source_col=source_col,
            patch_hint=(
                f"If `{forced_field}` and `{real_field}` belong to a "
                "file-local or inferred struct, try declaring the target-first "
                "field before the observed-first field. Do not apply this to "
                "fixed ABI structs."
            ),
            rationale=(
                "Field declaration order can change natural source emission "
                "order in local model structs, but it is a last-ranked probe "
                "because global layout changes have broad risk."
            ),
        ))

    return tuple(suggestions)


def _mode_and_caveat(finding: ScheduleDiffFinding | None) -> tuple[str, str]:
    if finding is None:
        return (
            "no-divergence",
            "no divergent scheduler-window decision was found",
        )
    if finding.margin is None:
        return (
            "structural",
            "priority data unavailable; suggestions are source-shape probes, "
            "not proven cost-margin flips",
        )
    if finding.margin <= 1:
        return (
            "local-order",
            "small reported margin; local source-order reshapes are likely "
            "worth trying first",
        )
    return (
        "structural",
        "large reported scheduler gap; prefer structural source reshapes over "
        "cosmetic reordering",
    )


def run(
    real_pcdump_text: str,
    forced_pcdump_text: str,
    *,
    function: str,
    force_schedule: str,
    source_text: str | None = None,
    source_file: str | None = None,
) -> ScheduleSuggestReport:
    diff = diff_schedule(
        real_pcdump_text,
        forced_pcdump_text,
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_file,
    )
    mode, caveat = _mode_and_caveat(diff.finding)
    suggestions = (
        _build_suggestions(diff.finding)
        if diff.finding is not None
        else ()
    )
    return ScheduleSuggestReport(
        function=function,
        mode=mode,
        caveat=caveat,
        finding=diff.finding,
        suggestions=suggestions,
    )


def _format_pick(cand: ScheduleCandidate | None) -> str:
    if cand is None:
        return "none"
    offset = "?" if cand.offset is None else f"0x{cand.offset:X}"
    expr = _candidate_expression(cand)
    suffix = f" expr={expr}" if expr else ""
    return f"{cand.role} {cand.opcode} {cand.operands} offset={offset}{suffix}"


def render_text(report: ScheduleSuggestReport) -> str:
    lines = [f"suggest-schedule-source - {report.function}"]
    lines.append(f"mode: {report.mode}")
    lines.append(f"caveat: {report.caveat}")
    if report.finding is None:
        lines.append("no source suggestions available")
        return "\n".join(lines)

    finding = report.finding
    lines.extend([
        "",
        f"divergence: step={finding.step} rule={finding.rule.raw}",
        f"  real picked {_format_pick(finding.real_pick)}",
        f"  forced picked {_format_pick(finding.forced_pick)}",
        f"  rationale: {finding.rationale}",
        "",
        "suggestions:",
    ])
    for suggestion in report.suggestions:
        loc = ""
        if suggestion.source_file and suggestion.source_line is not None:
            loc = f" source={suggestion.source_file}:{suggestion.source_line}"
            if suggestion.source_col is not None:
                loc += f":{suggestion.source_col}"
        lines.append(
            f"  {suggestion.rank}. {suggestion.kind} "
            f"mechanical={str(suggestion.mechanically_applicable).lower()}{loc}"
        )
        if suggestion.target_expression:
            lines.append(f"     target expr={suggestion.target_expression}")
        if suggestion.observed_expression:
            lines.append(f"     observed expr={suggestion.observed_expression}")
        lines.append(f"     patch: {suggestion.patch_hint}")
        lines.append(f"     why: {suggestion.rationale}")
    return "\n".join(lines)


def render_json(report: ScheduleSuggestReport) -> str:
    return json.dumps(asdict(report), indent=2)
