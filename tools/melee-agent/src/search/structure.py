"""Result models and payload helpers for structure search."""

from __future__ import annotations

import difflib
import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from src.mwcc_debug.source_patch import (
    find_function,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
)

DEFAULT_STRUCTURE_AXES = (
    "decl-order",
    "control-flow",
    "case-order",
    "statement-order",
)
SCORE_CAP_UNSCORED_REASON = "not scored due max-candidates cap"


@dataclass
class AxisSummary:
    axis: str
    status: str
    candidate_count: int = 0
    blocker: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


@dataclass
class StructureVariant:
    axis: str
    operator: str
    label: str
    status: str
    baseline_percent: float | None = None
    match_percent: float | None = None
    final_match_percent: float | None = None
    delta: float | None = None
    compile_status: str | None = None
    checkdiff_status: str | None = None
    unscored_reason: str | None = None
    path: str | None = None
    source_retained: str | None = None
    command: str = ""
    apply_hint: str = "review candidate source, then transfer verified function body"
    metadata: dict[str, Any] = field(default_factory=dict)
    rank: int | None = None

    def score_percent(self) -> float:
        value = self.final_match_percent
        if value is None:
            value = self.match_percent
        return -1.0 if value is None else float(value)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None and v != ""}


@dataclass(frozen=True)
class StructureScoreResult:
    label: str
    baseline_percent: float | None
    candidate_percent: float | None
    compile_status: str
    checkdiff_status: str | None = None
    unscored_reason: str | None = None
    structural: dict[str, Any] = field(default_factory=dict)


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return round(value - baseline, 6)


def rank_structure_variants(variants: list[StructureVariant]) -> list[StructureVariant]:
    ranked = sorted(
        variants,
        key=lambda variant: (
            0 if variant.score_percent() >= 100.0 and variant.status == "ok" else 1,
            -variant.score_percent(),
            -(variant.delta if variant.delta is not None else -9999.0),
            0 if variant.status == "ok" else 1,
            1 if variant.unscored_reason == SCORE_CAP_UNSCORED_REASON else 0,
            variant.axis,
            variant.operator,
            variant.label,
        ),
    )
    for index, variant in enumerate(ranked, 1):
        variant.rank = index
    return ranked


def run_structure_search(
    function: str,
    source_path: str | Path | None,
    output_dir: str | Path,
    axes: Sequence[str] = DEFAULT_STRUCTURE_AXES,
    baseline_percent: float | None = None,
    max_candidates: int = 24,
    timeout: int = 120,
    decl_order_runner: Callable[..., Any] | None = None,
    control_flow_runner: Callable[..., Any] | None = None,
    score_runner: (
        Callable[[list[StructureVariant]], list[StructureScoreResult]] | None
    ) = None,
    score_variants: bool = False,
) -> dict[str, Any]:
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    max_candidates = max(0, int(max_candidates))

    source: str | None = None
    source_display = ""
    resolved_source: Path | None = None
    source_read_error = ""
    if source_path is not None:
        resolved_source = Path(source_path).expanduser()
        source_display = str(resolved_source)
        try:
            source = resolved_source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            source_read_error = str(exc)

    requested_axes = tuple(axes or DEFAULT_STRUCTURE_AXES)
    axis_summaries: list[AxisSummary] = []
    variants: list[StructureVariant] = []

    for axis_name in requested_axes:
        axis = str(axis_name).strip()
        if axis == "case-order":
            if source is None:
                axis_summaries.append(
                    AxisSummary(
                        axis=axis,
                        status="blocked",
                        blocker="source-unavailable",
                        reason=source_read_error or "source file was not provided",
                    )
                )
                continue
            summary, axis_variants = generate_case_order_variants(
                source,
                function,
                output_path / "case-order",
                baseline_percent=baseline_percent,
                max_candidates=max_candidates,
            )
            axis_summaries.append(summary)
            variants.extend(axis_variants)
            continue

        if axis == "decl-order":
            command_args = [
                "melee-agent",
                "debug",
                "mutate",
                "decl-orders",
                function,
                "--strategy",
                "all",
                "--json",
            ]
            command = shlex.join(command_args)
            if decl_order_runner is None:
                if source is None:
                    summary, axis_variants = _blocked_axis(
                        axis,
                        "source-unavailable",
                        source_read_error or "source file was not provided",
                    )
                else:
                    summary, axis_variants = generate_decl_order_variants(
                        source,
                        function,
                        output_path / "decl-order",
                        baseline_percent=baseline_percent,
                        max_candidates=max_candidates,
                        command=command,
                    )
                axis_summaries.append(summary)
                variants.extend(axis_variants)
                continue
            try:
                payload = _axis_payload(
                    decl_order_runner,
                    function=function,
                    axis=axis,
                    args=command_args,
                    command=command,
                    output_dir=output_path / "decl-order",
                    max_candidates=max_candidates,
                    timeout=timeout,
                )
                axis_baseline = _payload_baseline_percent(payload)
                if baseline_percent is None and axis_baseline is not None:
                    baseline_percent = axis_baseline
                summary, axis_variants = normalize_decl_order_payload(
                    payload,
                    baseline_percent=baseline_percent,
                    command=command,
                )
            except _AxisCommandFailed as exc:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "axis-command-failed",
                    exc.reason,
                )
            except subprocess.TimeoutExpired as exc:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "axis-timeout",
                    _timeout_reason(exc, command, timeout),
                )
            except json.JSONDecodeError as exc:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "axis-json-error",
                    f"invalid JSON from {command}: {exc}",
                )
            axis_summaries.append(summary)
            variants.extend(axis_variants)
            continue

        if axis == "control-flow":
            axis_output_dir = output_path / "control-flow"
            command_args = [
                "melee-agent",
                "debug",
                "mutate",
                "control-flow-shape-search",
                "-f",
                function,
                "--json",
                "--output-dir",
                str(axis_output_dir),
                "--max-probes",
                str(max_candidates),
            ]
            command = shlex.join(command_args)
            if control_flow_runner is None:
                source_only_command = shlex.join(
                    command_args
                    + ["--no-compile-probes", "--no-score-match-percent"]
                )
                if source is None:
                    summary, axis_variants = _blocked_axis(
                        axis,
                        "source-unavailable",
                        source_read_error or "source file was not provided",
                    )
                else:
                    summary, axis_variants = generate_control_flow_variants(
                        source,
                        function,
                        axis_output_dir,
                        baseline_percent=baseline_percent,
                        max_candidates=max_candidates,
                        command=source_only_command,
                    )
                axis_summaries.append(summary)
                variants.extend(axis_variants)
                continue
            try:
                payload = _axis_payload(
                    control_flow_runner,
                    function=function,
                    axis=axis,
                    args=command_args,
                    command=command,
                    output_dir=axis_output_dir,
                    max_candidates=max_candidates,
                    timeout=timeout,
                )
                axis_baseline = _payload_baseline_percent(payload)
                if baseline_percent is None and axis_baseline is not None:
                    baseline_percent = axis_baseline
                summary, axis_variants = normalize_control_flow_payload(
                    payload,
                    baseline_percent=baseline_percent,
                    command=command,
                )
            except _AxisCommandFailed as exc:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "axis-command-failed",
                    exc.reason,
                )
            except subprocess.TimeoutExpired as exc:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "axis-timeout",
                    _timeout_reason(exc, command, timeout),
                )
            except json.JSONDecodeError as exc:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "axis-json-error",
                    f"invalid JSON from {command}: {exc}",
                )
            axis_summaries.append(summary)
            variants.extend(axis_variants)
            continue

        if axis == "statement-order":
            if source is None:
                summary, axis_variants = _blocked_axis(
                    axis,
                    "source-unavailable",
                    source_read_error or "source file was not provided",
                )
            else:
                summary, axis_variants = generate_statement_order_variants(
                    source,
                    function,
                    output_path / "statement-order",
                    baseline_percent=baseline_percent,
                    max_candidates=max_candidates,
                )
            axis_summaries.append(summary)
            variants.extend(axis_variants)
            continue

        axis_summaries.append(
            AxisSummary(
                axis=axis or "<empty>",
                status="blocked",
                blocker="unsupported-axis",
                reason="supported axes: " + ", ".join(DEFAULT_STRUCTURE_AXES),
            )
        )

    if score_variants and score_runner is not None:
        _score_generated_variants(variants, score_runner, max_candidates)
    else:
        _mark_generated_variants_unscored(variants, "scoring disabled")
    if baseline_percent is None:
        baseline_percent = _variant_baseline_percent(variants)

    payload = structure_payload(
        function=function,
        source=source_display,
        generated_source_dir=str(output_path),
        baseline_percent=baseline_percent,
        axes=axis_summaries,
        variants=variants,
    )
    payload["variants"] = payload["variants"][:max_candidates]
    return payload


def _variant_baseline_percent(variants: list[StructureVariant]) -> float | None:
    for variant in variants:
        if variant.baseline_percent is not None:
            return variant.baseline_percent
    return None


def _score_generated_variants(
    variants: list[StructureVariant],
    score_runner: Callable[[list[StructureVariant]], list[StructureScoreResult]],
    max_score_candidates: int,
) -> None:
    scoreable = [
        variant for variant in variants if _variant_needs_structure_score(variant)
    ]
    if not scoreable:
        return
    max_score_candidates = max(0, int(max_score_candidates))
    to_score = scoreable[:max_score_candidates]
    overflow = scoreable[max_score_candidates:]
    _mark_generated_variants_unscored(
        overflow,
        SCORE_CAP_UNSCORED_REASON,
    )
    if not to_score:
        return
    try:
        score_results = score_runner(to_score)
    except Exception as exc:
        _mark_generated_variants_unscored(
            to_score,
            f"score runner failed: {exc}",
        )
        return
    _apply_structure_scores(to_score, score_results)


def _variant_needs_structure_score(variant: StructureVariant) -> bool:
    return (
        variant.source_retained is not None
        and variant.status in {"candidate", "unscored"}
        and variant.final_match_percent is None
        and variant.match_percent is None
    )


def _mark_generated_variants_unscored(
    variants: list[StructureVariant],
    reason: str,
) -> None:
    for variant in variants:
        if not _variant_needs_structure_score(variant):
            continue
        variant.status = "unscored"
        variant.compile_status = variant.compile_status or "not-run"
        variant.unscored_reason = variant.unscored_reason or reason


def _apply_structure_scores(
    variants: list[StructureVariant],
    score_results: list[StructureScoreResult],
) -> None:
    scores_by_label = {result.label: result for result in score_results}
    for variant in variants:
        result = scores_by_label.get(variant.label)
        if result is None:
            variant.status = "unscored"
            variant.compile_status = variant.compile_status or "not-run"
            variant.unscored_reason = (
                variant.unscored_reason or "score result missing"
            )
            continue
        variant.compile_status = result.compile_status
        if result.checkdiff_status is not None:
            variant.checkdiff_status = result.checkdiff_status
        if result.baseline_percent is not None:
            variant.baseline_percent = result.baseline_percent
        if result.candidate_percent is not None:
            variant.match_percent = result.candidate_percent
            variant.final_match_percent = result.candidate_percent
            variant.delta = _delta(result.candidate_percent, variant.baseline_percent)
        if result.structural:
            variant.metadata = {
                **variant.metadata,
                "structural": dict(result.structural),
            }
        if (
            result.compile_status == "ok"
            and result.candidate_percent is not None
            and result.unscored_reason is None
        ):
            variant.status = "ok"
            continue
        variant.status = "unscored"
        variant.unscored_reason = (
            result.unscored_reason
            or f"candidate scoring did not produce a match percent ({result.compile_status})"
        )


def generate_decl_order_variants(
    source: str,
    function: str,
    output_dir: Path,
    *,
    baseline_percent: float | None,
    max_candidates: int,
    command: str,
) -> tuple[AxisSummary, list[StructureVariant]]:
    scope_map = get_decl_names_by_scope(source, function)
    selected_scope = (function,)
    selected_scope_reason = "function-top"
    if not scope_map.get(selected_scope):
        nested_scopes = [
            scope_path
            for scope_path, names in scope_map.items()
            if scope_path != (function,) and len(names) >= 2
        ]
        if not nested_scopes:
            nested_scopes = [
                scope_path
                for scope_path in scope_map
                if scope_path != (function,)
            ]
        if nested_scopes:
            selected_scope = nested_scopes[0]
            selected_scope_reason = "auto-nested"
    names = scope_map.get(selected_scope)
    if not names or len(names) < 2:
        return _blocked_axis(
            "decl-order",
            "no-decl-order-candidates",
            "could not find at least two reorderable declarations",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    variants: list[StructureVariant] = []
    for label, operator, perm in _decl_order_candidate_orders(names):
        if len(variants) >= max_candidates:
            break
        patched = reorder_decls_in_function_scope(
            source,
            function,
            selected_scope,
            perm,
        )
        if patched is None or patched == source:
            continue
        path = output_dir / f"{_safe_candidate_label(label)}.c"
        path.write_text(patched, encoding="utf-8")
        variants.append(
            StructureVariant(
                axis="decl-order",
                operator=f"decl-order-{operator}",
                label=label,
                status="candidate",
                baseline_percent=baseline_percent,
                path=str(path),
                source_retained=str(path),
                command=command,
                metadata={
                    "scope": "/".join(selected_scope),
                    "selected_scope_reason": selected_scope_reason,
                    "names": names,
                    "live_mutation": False,
                },
            )
        )

    if not variants:
        return _blocked_axis(
            "decl-order",
            "no-decl-order-candidates",
            "decl-order candidates were skipped by source safety checks",
        )
    return (
        AxisSummary(
            axis="decl-order",
            status="evaluated",
            candidate_count=len(variants),
        ),
        variants,
    )


def _decl_order_candidate_orders(
    names: list[str],
) -> list[tuple[str, str, list[int]]]:
    candidates: list[tuple[str, str, list[int]]] = []
    n = len(names)
    for index in range(1, n):
        perm = [index] + [i for i in range(n) if i != index]
        candidates.append((f"promote {names[index]}", "promote", perm))
    for index in range(n - 1):
        perm = [i for i in range(n) if i != index] + [index]
        candidates.append((f"demote {names[index]}", "demote", perm))
    for index in range(n - 1):
        perm = list(range(n))
        perm[index], perm[index + 1] = perm[index + 1], perm[index]
        candidates.append((
            f"swap {names[index]} <-> {names[index + 1]}",
            "swap",
            perm,
        ))
    return candidates


def generate_control_flow_variants(
    source: str,
    function: str,
    output_dir: Path,
    *,
    baseline_percent: float | None,
    max_candidates: int,
    command: str,
) -> tuple[AxisSummary, list[StructureVariant]]:
    from src.mwcc_debug.control_flow_shape import scan_control_flow_shape_probes

    probes, scan_status = scan_control_flow_shape_probes(
        source,
        function,
        max_probes=max_candidates,
    )
    if not probes:
        return _blocked_axis(
            "control-flow",
            str(scan_status.get("blocker") or "no-control-flow-shape-probes"),
            str(
                scan_status.get("reason")
                or "no safe control-flow source transform matched"
            ),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    variants: list[StructureVariant] = []
    for probe in probes[:max_candidates]:
        path = output_dir / f"{_safe_candidate_label(probe.label)}.c"
        path.write_text(probe.source_text, encoding="utf-8")
        variants.append(
            StructureVariant(
                axis="control-flow",
                operator=probe.operator,
                label=probe.label,
                status="candidate",
                baseline_percent=baseline_percent,
                path=str(path),
                source_retained=str(path),
                command=command,
                metadata={
                    "probe": probe.to_dict(),
                    "live_mutation": False,
                },
            )
        )

    return (
        AxisSummary(
            axis="control-flow",
            status="evaluated",
            candidate_count=len(variants),
        ),
        variants,
    )


_C_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_SPLIT_SHIFT_OR_PATTERNS = (
    re.compile(
        rf"(?m)^(?P<indent>[ \t]*)(?P<lhs>{_C_IDENT})\s*=\s*"
        rf"\(?\s*(?P=lhs)\s*<<\s*(?P<shift>[^)|;\n]+?)\s*\)?"
        rf"\s*\|\s*(?P<rhs>[^;\n]+?)\s*;"
    ),
    re.compile(
        rf"(?m)^(?P<indent>[ \t]*)(?P<lhs>{_C_IDENT})\s*=\s*"
        rf"(?P<rhs>[^|;\n]+?)\s*\|\s*"
        rf"\(?\s*(?P=lhs)\s*<<\s*(?P<shift>[^)|;\n]+?)\s*\)?\s*;"
    ),
)
_FUSE_SHIFT_OR_RE = re.compile(
    rf"(?m)^(?P<indent>[ \t]*)(?P<lhs>{_C_IDENT})\s*<<=\s*"
    rf"(?P<shift>[^;\n]+?)\s*;\s*\n"
    rf"(?P=indent)(?P=lhs)\s*\|=\s*(?P<rhs>[^;\n]+?)\s*;"
)
_LOCAL_SCALAR_TYPE_RE = re.compile(
    r"(?m)^\s*(?:(?:const|volatile)\s+)?"
    r"(?:(?:unsigned|signed)\s+)?"
    r"(?:char|short|int|long|float|double|bool|BOOL|"
    r"u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|size_t)"
    r"\s+(?P<decls>[^;(){}]+);"
)


def generate_statement_order_variants(
    source: str,
    function: str,
    output_dir: Path,
    baseline_percent: float | None,
    max_candidates: int = 12,
) -> tuple[AxisSummary, list[StructureVariant]]:
    function_span = find_function(source, function)
    if function_span is None:
        return _blocked_axis(
            "statement-order",
            "source-unavailable",
            "function was not found in source",
        )

    body_text = source[function_span.body_open + 1:function_span.body_close]
    if re.search(r"(?m)^\s*#", body_text):
        return _blocked_axis(
            "statement-order",
            "unsafe-statement-order-preprocessor",
            "preprocessor directives inside the function make statement spans unsafe",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    max_candidates = max(0, max_candidates)
    command = (
        f"melee-agent debug search structure -f {function} "
        f"--axis statement-order --max-candidates {max_candidates}"
    )
    variants: list[StructureVariant] = []
    seen_sources: set[str] = {source}

    def add_variant(
        *,
        operator: str,
        start: int,
        end: int,
        candidate_source: str,
        metadata: dict[str, Any],
    ) -> None:
        if len(variants) >= max_candidates:
            return
        if candidate_source in seen_sources:
            return
        seen_sources.add(candidate_source)
        label = f"{operator}-{sum(1 for row in variants if row.operator == operator)}"
        path = output_dir / f"{_safe_candidate_label(label)}.c"
        path.write_text(candidate_source, encoding="utf-8")
        touched_lines = _line_span(source, start, end)
        metadata = {
            **metadata,
            "touched_lines": touched_lines,
            "source_diff": _source_diff(source, candidate_source, label),
            "live_mutation": False,
        }
        variants.append(
            StructureVariant(
                axis="statement-order",
                operator=operator,
                label=label,
                status="candidate",
                baseline_percent=baseline_percent,
                path=str(path),
                source_retained=str(path),
                command=command,
                metadata=metadata,
            )
        )

    _generate_split_shift_or_statement_variants(
        source,
        function_span,
        add_variant,
    )
    _generate_fuse_shift_or_statement_variants(
        source,
        function_span,
        add_variant,
    )
    _generate_adjacent_statement_swap_variants(
        source,
        function_span,
        add_variant,
    )

    if not variants:
        return _blocked_axis(
            "statement-order",
            "no-statement-order-candidates",
            "no safe statement-order source transforms matched",
        )
    return (
        AxisSummary(
            axis="statement-order",
            status="evaluated",
            candidate_count=len(variants),
        ),
        variants,
    )


def _generate_split_shift_or_statement_variants(
    source: str,
    function_span,
    add_variant: Callable[..., None],
) -> None:
    masked_source = _mask_c_comments_and_literals(source)
    body_start = function_span.body_open + 1
    masked_body = masked_source[body_start:function_span.body_close]
    for pattern in _SPLIT_SHIFT_OR_PATTERNS:
        for match in pattern.finditer(masked_body):
            start = body_start + match.start()
            end = body_start + match.end()
            lhs = match.group("lhs")
            shift = _source_group(source, body_start, match, "shift")
            rhs = _source_group(source, body_start, match, "rhs")
            if _rhs_is_unsafe_for_statement_split(rhs, lhs):
                continue
            indent = match.group("indent")
            replacement = f"{indent}{lhs} <<= {shift};\n{indent}{lhs} |= {rhs};"
            candidate_source = source[:start] + replacement + source[end:]
            add_variant(
                operator="statement-order-split-shift-or",
                start=start,
                end=end,
                candidate_source=candidate_source,
                metadata={
                    "lhs": lhs,
                    "shift": shift,
                    "rhs": rhs,
                    "replacement": replacement,
                },
            )


def _generate_fuse_shift_or_statement_variants(
    source: str,
    function_span,
    add_variant: Callable[..., None],
) -> None:
    masked_source = _mask_c_comments_and_literals(source)
    body_start = function_span.body_open + 1
    masked_body = masked_source[body_start:function_span.body_close]
    for match in _FUSE_SHIFT_OR_RE.finditer(masked_body):
        start = body_start + match.start()
        end = body_start + match.end()
        if _c_comments(source[start:end]):
            continue
        lhs = match.group("lhs")
        shift = _source_group(source, body_start, match, "shift")
        rhs = _source_group(source, body_start, match, "rhs")
        if _rhs_is_unsafe_for_statement_split(rhs, lhs):
            continue
        indent = match.group("indent")
        replacement = f"{indent}{lhs} = ({lhs} << {shift}) | {rhs};"
        candidate_source = source[:start] + replacement + source[end:]
        add_variant(
            operator="statement-order-fuse-shift-or",
            start=start,
            end=end,
            candidate_source=candidate_source,
            metadata={
                "lhs": lhs,
                "shift": shift,
                "rhs": rhs,
                "replacement": replacement,
            },
        )


def _generate_adjacent_statement_swap_variants(
    source: str,
    function_span,
    add_variant: Callable[..., None],
) -> None:
    masked_source = _mask_c_comments_and_literals(source)
    parameter_scalars = _function_parameter_scalar_names(
        source,
        masked_source,
        function_span,
    )
    statements = _collect_direct_statement_spans(
        masked_source,
        function_span.body_open,
        function_span.body_close,
    )
    by_block: dict[int, list[tuple[int, int]]] = {}
    for block_open, start, end in statements:
        by_block.setdefault(block_open, []).append((start, end))
    for spans in by_block.values():
        for index, ((left_start, left_end), (right_start, right_end)) in enumerate(
            zip(spans, spans[1:])
        ):
            local_scalars = set(parameter_scalars)
            for decl_start, decl_end in spans[:index]:
                local_scalars.update(
                    _local_scalar_decl_statement_names(
                        masked_source[decl_start:decl_end]
                    )
                )
            if not local_scalars:
                continue
            left_text = source[left_start:left_end]
            right_text = source[right_start:right_end]
            left_access = _simple_local_assignment_access(left_text, local_scalars)
            right_access = _simple_local_assignment_access(right_text, local_scalars)
            if left_access is None or right_access is None:
                continue
            left_reads, left_writes = left_access
            right_reads, right_writes = right_access
            if (
                left_writes & right_writes
                or left_writes & right_reads
                or right_writes & left_reads
            ):
                continue
            between = source[left_end:right_start]
            replacement = right_text + between + left_text
            candidate_source = source[:left_start] + replacement + source[right_end:]
            add_variant(
                operator="statement-order-adjacent-swap",
                start=left_start,
                end=right_end,
                candidate_source=candidate_source,
                metadata={
                    "statement_order": [
                        right_text.strip(),
                        left_text.strip(),
                    ],
                    "local_scalars": sorted(local_scalars),
                },
            )


def _source_group(source: str, body_start: int, match: re.Match[str], group: str) -> str:
    return source[body_start + match.start(group):body_start + match.end(group)].strip()


def _rhs_is_unsafe_for_statement_split(rhs: str, lhs: str) -> bool:
    if re.search(rf"\b{re.escape(lhs)}\b", rhs):
        return True
    if "++" in rhs or "--" in rhs or "," in rhs or "?" in rhs:
        return True
    return (
        re.search(
            r"(?:<<=|>>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|(?<![=!<>])=(?!=))",
            rhs,
        )
        is not None
    )


def _function_parameter_scalar_names(source: str, masked_source: str, function_span) -> set[str]:
    names: set[str] = set()
    masked_signature = masked_source[function_span.sig_start:function_span.body_open]
    paren_open_rel = masked_signature.find("(")
    if paren_open_rel >= 0:
        paren_open = function_span.sig_start + paren_open_rel
        paren_close = _find_matching(masked_source, paren_open, "(", ")")
        if paren_close is not None:
            params = source[paren_open + 1:paren_close]
            for param in _split_top_level_commas(params):
                name = _local_scalar_declarator_name(param)
                if name is not None:
                    names.add(name)
    return names


def _local_scalar_decl_statement_names(masked_statement: str) -> set[str]:
    match = _LOCAL_SCALAR_TYPE_RE.search(masked_statement)
    if match is None:
        return set()
    names: set[str] = set()
    for declarator in _split_top_level_commas(match.group("decls")):
        name = _local_scalar_declarator_name(declarator)
        if name is not None:
            names.add(name)
    return names


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    for idx, ch in enumerate(text):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "," and paren_depth == 0 and bracket_depth == 0:
            parts.append(text[start:idx].strip())
            start = idx + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _local_scalar_declarator_name(declarator: str) -> str | None:
    text = declarator.strip()
    if not text or text == "void" or "*" in text or "[" in text or "(" in text:
        return None
    text = text.split("=", 1)[0].strip()
    tokens = re.findall(rf"\b({_C_IDENT})\b", text)
    if not tokens:
        return None
    name = tokens[-1]
    if name in {"const", "volatile", "unsigned", "signed", "struct", "enum"}:
        return None
    return name


def _collect_direct_statement_spans(
    masked_source: str,
    block_open: int,
    block_close: int,
) -> list[tuple[int, int, int]]:
    statements: list[tuple[int, int, int]] = []
    index = block_open + 1
    statement_start = index
    paren_depth = 0
    bracket_depth = 0
    while index < block_close:
        ch = masked_source[index]
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "{" and paren_depth == 0 and bracket_depth == 0:
            nested_close = _find_matching(masked_source, index, "{", "}")
            if nested_close is None or nested_close > block_close:
                return statements
            statements.extend(
                _collect_direct_statement_spans(masked_source, index, nested_close)
            )
            index = nested_close + 1
            statement_start = index
            continue
        elif ch == ";" and paren_depth == 0 and bracket_depth == 0:
            statements.append((block_open, statement_start, index + 1))
            statement_start = index + 1
        index += 1
    return statements


def _simple_local_assignment_access(
    statement: str,
    local_scalars: set[str],
) -> tuple[set[str], set[str]] | None:
    text = statement.strip()
    if not text:
        return None
    if re.match(r"(?:if|for|while|switch|do|return|break|continue|goto)\b", text):
        return None
    if re.match(
        r"(?:(?:const|volatile)\s+)?(?:(?:unsigned|signed)\s+)?"
        r"(?:char|short|int|long|float|double|bool|BOOL|"
        r"u8|s8|u16|s16|u32|s32|u64|s64|f32|f64|size_t)\b",
        text,
    ):
        return None
    if any(token in text for token in ("(", ")", "->", "*", "[", "]", ".", "++", "--")):
        return None
    match = re.fullmatch(rf"(?P<lhs>{_C_IDENT})\s*=\s*(?P<rhs>[^;]+);", text)
    if match is None:
        return None
    lhs = match.group("lhs")
    rhs = match.group("rhs")
    if lhs not in local_scalars:
        return None
    reads = set(re.findall(rf"\b({_C_IDENT})\b", rhs))
    if not reads <= local_scalars:
        return None
    return reads, {lhs}


def _line_span(source: str, start: int, end: int) -> dict[str, int]:
    return {
        "start": source.count("\n", 0, start) + 1,
        "end": source.count("\n", 0, max(start, end - 1)) + 1,
    }


def _source_diff(source: str, candidate_source: str, label: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            source.splitlines(),
            candidate_source.splitlines(),
            fromfile="original",
            tofile=label,
            lineterm="",
            n=2,
        )
    )


def _safe_candidate_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label.strip()).strip("-")
    return safe or "candidate"


def render_structure_text(payload: dict[str, Any]) -> str:
    lines = [f"structure search - {payload.get('function', '')}"]
    source = payload.get("source")
    if source:
        lines.append(f"source: {source}")
    generated_source_dir = payload.get("generated_source_dir")
    if generated_source_dir:
        lines.append(f"generated_source_dir: {generated_source_dir}")
    if payload.get("baseline_percent") is not None:
        lines.append(f"baseline: {float(payload['baseline_percent']):.5f}")

    axes = payload.get("axes") or []
    if axes:
        axis_parts = []
        for axis in axes:
            if not isinstance(axis, dict):
                continue
            part = f"{axis.get('axis', '')}={axis.get('status', '')}"
            if axis.get("candidate_count") is not None:
                part += f"({axis['candidate_count']})"
            if axis.get("blocker"):
                part += f"[{axis['blocker']}]"
            axis_parts.append(part)
        if axis_parts:
            lines.append("axes: " + ", ".join(axis_parts))

    stop_condition = payload.get("stop_condition") or {}
    if isinstance(stop_condition, dict):
        stop_line = f"stop condition: {stop_condition.get('kind', '')}"
        if stop_condition.get("blocker"):
            stop_line += f" ({stop_condition['blocker']})"
        if stop_condition.get("reason"):
            stop_line += f" - {stop_condition['reason']}"
        lines.append(stop_line)

    variants = payload.get("variants") or []
    lines.append("top variants:")
    if not variants:
        lines.append("  none")
    for index, variant in enumerate(variants, 1):
        if not isinstance(variant, dict):
            continue
        rank = variant.get("rank") or index
        axis = variant.get("axis", "")
        operator = variant.get("operator", "")
        label = variant.get("label", "")
        status = variant.get("status", "")
        line = f"  {rank}. {axis} / {operator} - {label} [{status}]"
        match_percent = variant.get("final_match_percent")
        if match_percent is None:
            match_percent = variant.get("match_percent")
        if match_percent is not None:
            line += f" match: {float(match_percent):.5f}"
        if variant.get("delta") is not None:
            line += f" delta: {float(variant['delta']):+.5f}"
        lines.append(line)
        if variant.get("source_retained"):
            lines.append(f"     source: {variant['source_retained']}")
        if variant.get("command"):
            lines.append(f"     rerun: {variant['command']}")
    return "\n".join(lines)


def normalize_control_flow_payload(
    payload: dict[str, Any],
    *,
    baseline_percent: float | None,
    command: str,
) -> tuple[AxisSummary, list[StructureVariant]]:
    variants: list[StructureVariant] = []
    for row in payload.get("variants") or []:
        if not isinstance(row, dict):
            continue
        match_percent = _float_or_none(row.get("match_percent"))
        final_match_percent = _float_or_none(row.get("final_match_percent"))
        score = final_match_percent if final_match_percent is not None else match_percent
        metadata: dict[str, Any] = {}
        if "probe" in row:
            metadata["probe"] = row.get("probe")
        if row.get("match_percent_error") is not None:
            metadata["match_percent_error"] = row.get("match_percent_error")
        if row.get("error") is not None:
            metadata["error"] = row.get("error")
        variants.append(
            StructureVariant(
                axis="control-flow",
                operator=str(row.get("operator") or "control-flow-shape"),
                label=str(row.get("label") or "control-flow"),
                status=str(row.get("status") or "unknown"),
                baseline_percent=baseline_percent,
                match_percent=match_percent,
                final_match_percent=final_match_percent,
                delta=_delta(score, baseline_percent),
                path=_str_or_none(row.get("path")),
                source_retained=_str_or_none(row.get("source_retained")),
                command=command,
                metadata=metadata,
            )
        )
    blocker = _payload_blocker(payload)
    if variants:
        axis = AxisSummary(
            axis="control-flow",
            status="evaluated",
            candidate_count=len(variants),
        )
    else:
        axis = AxisSummary(
            axis="control-flow",
            status="blocked" if blocker else "evaluated",
            blocker=blocker,
            reason=_payload_reason(payload),
        )
    return axis, variants


def normalize_decl_order_payload(
    payload: dict[str, Any],
    *,
    baseline_percent: float | None,
    command: str,
) -> tuple[AxisSummary, list[StructureVariant]]:
    variants: list[StructureVariant] = []
    for row in _decl_order_result_rows(payload):
        if not isinstance(row, dict) or row.get("skipped"):
            continue
        match_percent = _float_or_none(row.get("match_pct"))
        if match_percent is None:
            match_percent = _float_or_none(row.get("best_pct"))
        delta = _float_or_none(row.get("delta"))
        if delta is None:
            delta = _delta(match_percent, baseline_percent)
        label = str(row.get("label") or "decl-order")
        variants.append(
            StructureVariant(
                axis="decl-order",
                operator=_decl_order_operator(row, label),
                label=label,
                status=str(row.get("status") or "ok"),
                baseline_percent=baseline_percent,
                match_percent=match_percent,
                final_match_percent=match_percent,
                delta=delta,
                path=_str_or_none(row.get("path")),
                source_retained=None,
                command=_strip_command_flag(command, "--keep-best"),
                metadata=_decl_order_metadata(row),
            )
        )
    blocker = _payload_blocker(payload)
    if variants:
        axis = AxisSummary(
            axis="decl-order",
            status="evaluated",
            candidate_count=len(variants),
        )
    else:
        axis = AxisSummary(
            axis="decl-order",
            status="blocked" if blocker else "evaluated",
            blocker=blocker,
            reason=_payload_reason(payload),
        )
    return axis, variants


@dataclass
class _SwitchSpan:
    switch_start: int
    body_open: int
    body_close: int
    line: int


@dataclass
class _CaseLabel:
    start: int
    end: int
    value: str


@dataclass
class _CaseArm:
    start: int
    end: int
    labels: list[str]
    text: str

    @property
    def display_label(self) -> str:
        return "/".join(self.labels)


def generate_case_order_variants(
    source: str,
    function: str,
    output_dir: Path,
    baseline_percent: float | None,
    max_candidates: int = 12,
) -> tuple[AxisSummary, list[StructureVariant]]:
    function_span = find_function(source, function)
    if function_span is None:
        return _blocked_case_order("source-unavailable")

    masked_source = _mask_c_comments_and_literals(source)
    switch = _find_first_switch(
        source,
        masked_source,
        function_span.body_open,
        function_span.body_close,
    )
    if switch is None:
        return _blocked_case_order("no-case-order-probes")

    switch_text = source[switch.body_open + 1 : switch.body_close]
    if re.search(r"(?m)^\s*#", switch_text):
        return _blocked_case_order("unsafe-switch-preprocessor")

    masked_switch = masked_source[switch.switch_start : switch.body_close]
    if len(list(re.finditer(r"\bswitch\s*\(", masked_switch))) > 1:
        return _blocked_case_order("unsafe-switch-nested-ambiguous")

    if _comments_contain_fallthrough(switch_text):
        return _blocked_case_order("unsafe-switch-fallthrough")

    body_start = switch.body_open + 1
    body_end = switch.body_close
    arms = _parse_switch_arms(source, masked_source, body_start, body_end)
    if len(arms) < 2:
        return _blocked_case_order("no-case-order-probes")
    body_prefix = source[body_start : arms[0].start]
    body_suffix = source[arms[-1].end : body_end]
    if (
        _has_user_label_or_goto(body_prefix)
        or _has_user_label_or_goto(body_suffix)
        or any(_has_user_label_or_goto(arm.text, strip_case_labels=True) for arm in arms)
    ):
        return _blocked_case_order("unsafe-switch-cross-label")
    if any(not _case_arm_is_terminal(arm.text) for arm in arms):
        return _blocked_case_order("unsafe-switch-fallthrough")

    output_dir.mkdir(parents=True, exist_ok=True)

    variants: list[StructureVariant] = []
    max_candidates = max(0, max_candidates)
    command = (
        f"melee-agent debug search structure -f {function} "
        f"--axis case-order --max-candidates {max_candidates}"
    )
    original_labels = [arm.display_label for arm in arms]

    for strategy, order in _case_order_candidate_orders(len(arms)):
        if len(variants) >= max_candidates:
            break
        new_labels = [arms[index].display_label for index in order]
        new_body = body_prefix + "".join(arms[index].text for index in order) + body_suffix
        candidate_source = source[:body_start] + new_body + source[body_end:]
        label = f"case-order-{strategy}-{len(variants)}"
        path = output_dir / f"{label}.c"
        path.write_text(candidate_source, encoding="utf-8")
        variants.append(
            StructureVariant(
                axis="case-order",
                operator=f"case-order-{strategy}",
                label=label,
                status="candidate",
                baseline_percent=baseline_percent,
                path=str(path),
                source_retained=str(path),
                command=command,
                metadata={
                    "strategy": strategy,
                    "switch_line": switch.line,
                    "original_labels": original_labels,
                    "case_order": new_labels,
                },
            )
        )

    if not variants:
        return _blocked_case_order("no-case-order-probes")

    return (
        AxisSummary(
            axis="case-order",
            status="evaluated",
            candidate_count=len(variants),
        ),
        variants,
    )


def structure_payload(
    *,
    function: str,
    source: str,
    generated_source_dir: str,
    baseline_percent: float | None,
    axes: list[AxisSummary],
    variants: list[StructureVariant],
) -> dict[str, Any]:
    ranked = rank_structure_variants(variants)
    stop_condition = _structure_stop_condition(ranked)
    return {
        "function": function,
        "source": source,
        "generated_source_dir": generated_source_dir,
        "baseline_percent": baseline_percent,
        "axes": [axis.to_dict() for axis in axes],
        "variants": [variant.to_dict() for variant in ranked],
        "future_axes": [
            {"axis": "inline-boundary", "status": "not-implemented"},
            {"axis": "loop-shape-expanded", "status": "not-implemented"},
        ],
        "stop_condition": stop_condition,
    }


def _blocked_case_order(
    blocker: str,
    reason: str = "",
) -> tuple[AxisSummary, list[StructureVariant]]:
    return (
        AxisSummary(
            axis="case-order",
            status="blocked",
            blocker=blocker,
            reason=reason,
        ),
        [],
    )


def _mask_c_comments_and_literals(text: str) -> str:
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    if text[i] != "\n":
                        out[i] = " "
                    if text[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    out[i] = " "
                    i += 1
                continue
            if text[i + 1] == "*":
                start = i
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                end = min(n, i + 2)
                for index in range(start, end):
                    if text[index] != "\n":
                        out[index] = " "
                i = end
                continue
        i += 1
    return "".join(out)


def _find_first_switch(
    source: str,
    masked_source: str,
    body_open: int,
    body_close: int,
) -> _SwitchSpan | None:
    function_body = masked_source[body_open + 1 : body_close]
    for match in re.finditer(r"\bswitch\s*\(", function_body):
        switch_start = body_open + 1 + match.start()
        paren_open = body_open + 1 + match.end() - 1
        paren_close = _find_matching(masked_source, paren_open, "(", ")")
        if paren_close is None:
            continue
        brace_open = _skip_whitespace(masked_source, paren_close + 1)
        if brace_open >= body_close or masked_source[brace_open] != "{":
            continue
        switch_close = _find_matching(masked_source, brace_open, "{", "}")
        if switch_close is None or switch_close > body_close:
            continue
        return _SwitchSpan(
            switch_start=switch_start,
            body_open=brace_open,
            body_close=switch_close,
            line=source.count("\n", 0, switch_start) + 1,
        )
    return None


def _find_matching(text: str, start: int, opener: str, closer: str) -> int | None:
    if start >= len(text) or text[start] != opener:
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _comments_contain_fallthrough(text: str) -> bool:
    return any(
        re.search(r"fall\s*-?\s*through|fallthrough|falls?\s+through", comment, re.I)
        for comment in _c_comments(text)
    )


def _c_comments(text: str) -> list[str]:
    comments: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] in ("'", '"'):
            quote = text[i]
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if text[i] == "/" and i + 1 < n:
            if text[i + 1] == "/":
                start = i + 2
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                comments.append(text[start:i])
                continue
            if text[i + 1] == "*":
                start = i + 2
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                comments.append(text[start:i])
                i = min(n, i + 2)
                continue
        i += 1
    return comments


def _parse_switch_arms(
    source: str,
    masked_source: str,
    body_start: int,
    body_end: int,
) -> list[_CaseArm]:
    labels = _find_case_labels(masked_source, body_start, body_end)
    if not labels:
        return []

    groups: list[list[_CaseLabel]] = []
    current: list[_CaseLabel] = [labels[0]]
    for label in labels[1:]:
        between = masked_source[current[-1].end : label.start]
        if between.strip():
            groups.append(current)
            current = [label]
        else:
            current.append(label)
    groups.append(current)

    arms: list[_CaseArm] = []
    for index, group in enumerate(groups):
        start = group[0].start
        end = groups[index + 1][0].start if index + 1 < len(groups) else body_end
        arms.append(
            _CaseArm(
                start=start,
                end=end,
                labels=[label.value for label in group],
                text=source[start:end],
            )
        )
    return arms


def _find_case_labels(masked_source: str, body_start: int, body_end: int) -> list[_CaseLabel]:
    masked_body = masked_source[body_start:body_end]
    depths = _brace_depths(masked_body)
    labels: list[_CaseLabel] = []
    for match in re.finditer(r"\b(case|default)\b", masked_body):
        if depths[match.start()] != 0:
            continue
        end = _case_label_end(masked_body, match.start(), match.group(1))
        if end is None:
            continue
        label_text = masked_body[match.start() : end]
        labels.append(
            _CaseLabel(
                start=body_start + match.start(),
                end=body_start + end,
                value=_case_label_value(label_text),
            )
        )
    return labels


def _brace_depths(text: str) -> list[int]:
    depths = [0] * (len(text) + 1)
    depth = 0
    for index, ch in enumerate(text):
        depths[index] = depth
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    depths[len(text)] = depth
    return depths


def _case_label_end(masked_text: str, start: int, kind: str) -> int | None:
    index = start + len(kind)
    paren_depth = 0
    bracket_depth = 0
    ternary_depth = 0
    while index < len(masked_text):
        ch = masked_text[index]
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif (
            kind == "case"
            and ch == "?"
            and paren_depth == 0
            and bracket_depth == 0
        ):
            ternary_depth += 1
        elif ch == ":" and paren_depth == 0 and bracket_depth == 0:
            if kind == "case" and ternary_depth:
                ternary_depth -= 1
            else:
                return index + 1
        elif kind == "default" and ch not in " \t\r\n":
            return None
        index += 1
    return None


def _case_label_value(label_text: str) -> str:
    label_text = label_text.strip()
    if label_text.startswith("default"):
        return "default"
    value = label_text[len("case") :].strip()
    if value.endswith(":"):
        value = value[:-1].strip()
    return " ".join(value.split())


def _case_arm_is_terminal(arm_text: str) -> bool:
    masked_arm = _mask_c_comments_and_literals(arm_text)
    body = _strip_leading_case_labels(masked_arm)
    return _statement_text_is_terminal(body)


def _strip_leading_case_labels(masked_text: str) -> str:
    index = 0
    while index < len(masked_text):
        index = _skip_whitespace(masked_text, index)
        match = re.match(r"(case|default)\b", masked_text[index:])
        if match is None:
            break
        end = _case_label_end(masked_text, index, match.group(1))
        if end is None:
            break
        index = end
    return masked_text[index:]


def _has_user_label_or_goto(text: str, *, strip_case_labels: bool = False) -> bool:
    masked_text = _mask_c_comments_and_literals(text)
    if strip_case_labels:
        masked_text = _strip_leading_case_labels(masked_text)
    if re.search(r"\bgoto\s+[A-Za-z_]\w*\s*;", masked_text):
        return True
    depths = _brace_depths(masked_text)
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*:", masked_text):
        if depths[match.start()] != 0:
            continue
        label = match.group(1)
        if label not in {"case", "default"}:
            return True
    return False


def _statement_text_is_terminal(masked_text: str) -> bool:
    text = masked_text.strip()
    while _is_wrapped_block(text):
        text = text[1:-1].strip()
    if not text:
        return False

    semi_index = _last_top_level_semicolon(text)
    if semi_index is None:
        return False
    statement_start = _previous_top_level_delimiter_end(text, semi_index)
    tail = text[statement_start : semi_index + 1].strip()
    return bool(
        re.fullmatch(
            r"break\s*;|continue\s*;|goto\s+[A-Za-z_]\w*\s*;|return(?:\s+[^;{}]*)?;",
            tail,
            re.S,
        )
    )


def _is_wrapped_block(masked_text: str) -> bool:
    if not (masked_text.startswith("{") and masked_text.endswith("}")):
        return False
    return _find_matching(masked_text, 0, "{", "}") == len(masked_text) - 1


def _last_top_level_semicolon(masked_text: str) -> int | None:
    depths = _brace_depths(masked_text)
    paren_depth = 0
    bracket_depth = 0
    last: int | None = None
    for index, ch in enumerate(masked_text):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == ";" and depths[index] == 0 and paren_depth == 0 and bracket_depth == 0:
            last = index
    return last


def _previous_top_level_delimiter_end(masked_text: str, before: int) -> int:
    depths = _brace_depths(masked_text)
    paren_depth = 0
    bracket_depth = 0
    delimiter_end = 0
    for index, ch in enumerate(masked_text[:before]):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif (
            ch in ";}"
            and depths[index] == 0
            and paren_depth == 0
            and bracket_depth == 0
        ):
            delimiter_end = index + 1
    return delimiter_end


def _case_order_candidate_orders(count: int) -> list[tuple[str, list[int]]]:
    original = list(range(count))
    candidates: list[tuple[str, list[int]]] = []

    def add_unique(strategy: str, order: list[int]) -> None:
        if order == original:
            return
        order_key = tuple(order)
        if any(tuple(existing_order) == order_key for _, existing_order in candidates):
            return
        candidates.append((strategy, order))

    for index in range(count - 1):
        order = original.copy()
        order[index], order[index + 1] = order[index + 1], order[index]
        add_unique("adjacent-swap", order)
    for index in range(1, count):
        order = original.copy()
        arm = order.pop(index)
        order.insert(0, arm)
        add_unique("promote", order)
    for index in range(count - 1):
        order = original.copy()
        arm = order.pop(index)
        order.append(arm)
        add_unique("demote", order)
    return candidates


def _decl_order_result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    results = payload.get("results")
    if isinstance(results, list):
        rows.extend(row for row in results if isinstance(row, dict))
    for round_payload in payload.get("rounds") or []:
        if not isinstance(round_payload, dict):
            continue
        round_results = round_payload.get("results")
        if isinstance(round_results, list):
            rows.extend(row for row in round_results if isinstance(row, dict))
    return rows


def _decl_order_operator(row: dict[str, Any], label: str) -> str:
    strategy = str(row.get("strategy") or "").strip()
    if not strategy:
        strategy = label.split(maxsplit=1)[0] if label.strip() else "candidate"
    return f"decl-order-{strategy}"


def _decl_order_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("strategy", "skip_reason"):
        if row.get(key) is not None:
            metadata[key] = row[key]
    return metadata


def _payload_blocker(payload: dict[str, Any]) -> str | None:
    blocker = payload.get("blocker")
    if blocker:
        return str(blocker)
    stop_condition = payload.get("stop_condition")
    if isinstance(stop_condition, dict) and stop_condition.get("blocker"):
        return str(stop_condition["blocker"])
    return None


def _payload_reason(payload: dict[str, Any]) -> str:
    reason = payload.get("reason")
    if reason:
        return str(reason)
    stop_condition = payload.get("stop_condition")
    if isinstance(stop_condition, dict) and stop_condition.get("reason"):
        return str(stop_condition["reason"])
    return ""


def _strip_command_flag(command: str, flag: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command.replace(flag, "").strip()
    return shlex.join(part for part in parts if part != flag)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _structure_stop_condition(variants: list[StructureVariant]) -> dict[str, Any]:
    if any(
        variant.score_percent() >= 100.0
        or (variant.delta is not None and variant.delta > 0)
        for variant in variants
    ):
        return {
            "kind": "improved",
            "blocker": None,
            "reason": "one or more structure variants improved over baseline or reached 100% match",
        }
    if any(
        variant.status in {"candidate", "unscored"}
        and variant.match_percent is None
        and variant.final_match_percent is None
        and variant.delta is None
        for variant in variants
    ):
        return {
            "kind": "candidates-generated",
            "blocker": None,
            "reason": "unscored source candidates were generated and need compile/checkdiff verification",
        }
    return {
        "kind": "no-improvement",
        "blocker": None,
        "reason": "no structure variant improved over baseline",
    }


class _AxisCommandFailed(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _axis_payload(
    runner: Callable[..., Any] | None,
    *,
    function: str,
    axis: str,
    args: list[str],
    command: str,
    output_dir: Path,
    max_candidates: int,
    timeout: int,
) -> dict[str, Any]:
    if runner is None:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return _payload_from_completed_process(proc, command=command)

    result = _call_injected_runner(
        runner,
        function=function,
        axis=axis,
        args=args,
        command=command,
        output_dir=output_dir,
        max_candidates=max_candidates,
        timeout=timeout,
    )
    return _coerce_axis_payload(result, command=command)


def _call_injected_runner(
    runner: Callable[..., Any],
    **kwargs: Any,
) -> Any:
    try:
        return runner(**kwargs)
    except TypeError as exc:
        try:
            return runner(kwargs["args"], timeout=kwargs["timeout"])
        except TypeError:
            try:
                return runner(kwargs["args"])
            except TypeError:
                raise exc


def _payload_from_completed_process(
    proc: subprocess.CompletedProcess[str],
    *,
    command: str,
) -> dict[str, Any]:
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if detail:
            detail = detail.splitlines()[-1]
        raise _AxisCommandFailed(
            f"{command} exited {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    return _parse_json_stdout(proc.stdout)


def _coerce_axis_payload(result: Any, *, command: str) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        return _parse_json_stdout(result)
    if isinstance(result, subprocess.CompletedProcess):
        return _payload_from_completed_process(result, command=command)
    if all(hasattr(result, attr) for attr in ("returncode", "stdout", "stderr")):
        proc = subprocess.CompletedProcess(
            args=command,
            returncode=int(result.returncode),
            stdout=str(result.stdout),
            stderr=str(result.stderr),
        )
        return _payload_from_completed_process(proc, command=command)
    raise _AxisCommandFailed(f"{command} returned unsupported payload type")


def _parse_json_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise _AxisCommandFailed("JSON payload was not an object")
    return payload


def _blocked_axis(
    axis: str,
    blocker: str,
    reason: str,
) -> tuple[AxisSummary, list[StructureVariant]]:
    return (
        AxisSummary(
            axis=axis,
            status="blocked",
            blocker=blocker,
            reason=reason,
        ),
        [],
    )


def _timeout_reason(
    exc: subprocess.TimeoutExpired,
    command: str,
    timeout: int,
) -> str:
    elapsed = exc.timeout if exc.timeout is not None else timeout
    return f"{command} timed out after {elapsed}s"


def _payload_baseline_percent(payload: dict[str, Any]) -> float | None:
    for key in (
        "baseline_percent",
        "baseline_pct",
        "baseline_match_percent",
        "baseline_fuzzy_match_percent",
    ):
        value = _float_or_none(payload.get(key))
        if value is not None:
            return value
    return None
