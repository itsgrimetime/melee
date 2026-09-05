"""Post-ceiling baseline escape candidates after allocator ceilings.

This module is intentionally diagnostic-only. It consumes terminal artifacts
from allocator-ceiling and retained-frontier lanes, then emits bounded source
baselines for existing scoring commands to validate.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .source_hunks import diff_line_hunks
from .source_patch import find_function

KIND = "post-ceiling-baseline-escape"
TERMINAL_BLOCKER = "current-source-shape-ceiling"
DRAW_TERMINAL_KIND = "no-post-ceiling-draw-source-family"
SORT_TERMINAL_KIND = "no-post-ceiling-sort-source-family"
TERMINAL_KIND = DRAW_TERMINAL_KIND
TERMINAL_REASON = f"{TERMINAL_KIND}/{TERMINAL_BLOCKER}"
SUPPRESSION_FAMILY = "post-ceiling-baseline-escape"
CONTINUATION_KIND = "post-ceiling-baseline-escape-continuation"
CONTINUATION_FAMILY = "post-ceiling-baseline-escape-continuation"
CONTINUATION_TERMINAL_KIND = "post-ceiling-continuation-exhausted"
CONTINUATION_TERMINAL_REASON = (
    "post-ceiling-continuation-exhausted/all-candidate-routes-unsupported"
)
FINAL_TERMINAL_KIND = "post-ceiling-all-frontiers-exhausted"
FINAL_TERMINAL_REASON = f"{FINAL_TERMINAL_KIND}/{TERMINAL_BLOCKER}"
FINAL_SYNTHESIS_FAMILY = "post-ceiling-final-synthesis"
SOURCE_FAMILY_DISCOVERY_KIND = "post-ceiling-source-family-discovery"
SOURCE_FAMILY_DISCOVERY_FAMILY = "post-ceiling-source-family-discovery"
SOURCE_FAMILY_DISCOVERY_TERMINAL_KIND = (
    "post-ceiling-source-family-discovery-exhausted"
)
SOURCE_FAMILY_DISCOVERY_TERMINAL_REASON = (
    f"{SOURCE_FAMILY_DISCOVERY_TERMINAL_KIND}/bounded-source-spans-missing"
)
SOURCE_FAMILY_PROGRESS_TERMINAL_KIND = (
    "post-ceiling-source-family-progress-plateau"
)
SOURCE_FAMILY_PROGRESS_TERMINAL_REASON = (
    f"{SOURCE_FAMILY_PROGRESS_TERMINAL_KIND}/{TERMINAL_BLOCKER}"
)
FORCE_CONFLICT_TERMINAL_KIND = "post-ceiling-force-map-conflict"
FORCE_CONFLICT_TERMINAL_REASON = (
    "post-ceiling-force-map-conflict/ambiguous-score-force-targets"
)
FORCE_CONFLICT_BLOCKER = "ambiguous-score-force-targets"

_DRAW_ALLOCATOR_TERMINAL_REASON = "expression-scored-fpr-allocator-ceiling"
_SORT_ALLOCATOR_LEGACY_TERMINAL_REASON = "residual-case-c-source-repair-exhausted"
_SORT_ALLOCATOR_RETAINED_TERMINAL_REASON = (
    "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"
)
_SORT_ALLOCATOR_TERMINAL_REASONS = {
    _SORT_ALLOCATOR_LEGACY_TERMINAL_REASON,
    _SORT_ALLOCATOR_RETAINED_TERMINAL_REASON,
}
_EXPRESSION_TERMINAL_KIND = "no-expression-progress-after-row-fsubs-and-support-orders"
_RETAINED_EXHAUSTED_STATUS = "all-known-frontiers-exhausted"
_SORT_FUNCTION = "mnDiagram_SortNamesByKOs"
_SORT_SOURCE_FUNCTION = "mnDiagram_8023FC28"
_SOURCE_FUNCTION_ALIASES = {
    _SORT_FUNCTION: _SORT_SOURCE_FUNCTION,
}
_KNOWN_SOURCE_PATHS = {
    _SORT_FUNCTION: Path("src/melee/mn/mndiagram.c"),
}
_SUPPRESSED_FAMILY_KEYS = (
    "row_fsubs_owner_repair",
    "protected_expression_row_product_generation",
    "row_offset_first_scaled_ownership",
    "product_sink_ownership",
    "product_operand_ownership",
    "row_offset_sink_branch_ownership",
    "digit_guarded_statement_motion",
    "paired_row_product_recombine",
    "retained_fpr_case_c_target_live_range_repair",
    "retained-source-select-order-repair",
)
_SORT_SUPPRESSED_FAMILY_KEYS = (
    "retained-source-case-c-lower-drift-residual",
    "indexed_byte_address_temp_steering",
    "copy-survived-pointer-reset",
    "node-set-split",
    "source-owner-backtracking",
    "common-subexpr-coalesce-pointer-base",
)


@dataclass(frozen=True)
class BaselineEscapeCandidate:
    candidate_id: str
    family: str
    strategy: str
    priority: int
    rationale: str
    expected_effect: str
    novelty_reason: str
    source_text: str
    validation_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self, *, base_source: str, include_source: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "strategy": self.strategy,
            "priority": self.priority,
            "rationale": self.rationale,
            "expected_effect": self.expected_effect,
            "novelty_reason": self.novelty_reason,
            "overlap_blockers": [],
            "source_hunks": [
                hunk.to_dict() for hunk in diff_line_hunks(
                    base_source,
                    self.source_text,
                    hunk_prefix=f"{self.candidate_id}-h",
                )
            ],
            "validation_metadata": dict(self.validation_metadata),
        }
        if include_source:
            data["source_text"] = self.source_text
        return data


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def resolve_baseline_source_path(
    *,
    repo_root: Path,
    function: str,
    source_file: Path | None = None,
    allocator_ceiling: Mapping[str, Any] | None = None,
    expression_interferer: Mapping[str, Any] | None = None,
    retained_frontiers: Mapping[str, Any] | None = None,
    supplemental_evidence: Sequence[Mapping[str, Any]] = (),
) -> Path | None:
    """Resolve the retained source baseline in the order documented by #965."""

    if source_file is not None:
        return _resolve_existing_path(source_file, repo_root=repo_root)

    candidates: list[Any] = []
    if isinstance(allocator_ceiling, Mapping):
        candidates.append(
            _nested_get(
                allocator_ceiling,
                (
                    "expression_interferer_terminal",
                    "source_generation",
                    "source_file",
                ),
            )
        )
    if isinstance(expression_interferer, Mapping):
        candidates.append(
            _nested_get(expression_interferer, ("source_generation", "source_file"))
        )
    candidates.extend(
        _source_candidates_from_retained_frontiers(retained_frontiers, function=function)
    )
    if isinstance(allocator_ceiling, Mapping):
        candidates.extend(_retained_candidate_paths(allocator_ceiling))
    if isinstance(expression_interferer, Mapping):
        candidates.extend(_retained_candidate_paths(expression_interferer))
    for payload in supplemental_evidence:
        if isinstance(payload, Mapping):
            candidates.extend(_retained_candidate_paths(payload))
    if function in _KNOWN_SOURCE_PATHS:
        candidates.append(_KNOWN_SOURCE_PATHS[function])

    for candidate in candidates:
        if not isinstance(candidate, (str, Path)):
            continue
        try:
            return _resolve_existing_path(Path(candidate), repo_root=repo_root)
        except ValueError:
            continue
    return None


def generate_baseline_escape_candidates(
    source_text: str,
    *,
    function: str,
    source_function: str | None = None,
    allocator_ceiling: Mapping[str, Any] | None = None,
    expression_interferer: Mapping[str, Any] | None = None,
    retained_frontiers: Mapping[str, Any] | None = None,
    supplemental_evidence: Sequence[Mapping[str, Any]] = (),
    score_payloads: Sequence[Mapping[str, Any]] = (),
    max_candidates: int = 12,
    include_source: bool = False,
    validation_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and optionally classify post-ceiling baseline-escape candidates."""

    evidence = _normalize_evidence(
        function=function,
        allocator_ceiling=allocator_ceiling,
        expression_interferer=expression_interferer,
        retained_frontiers=retained_frontiers,
        supplemental_evidence=supplemental_evidence,
    )
    function_name = source_function or _SOURCE_FUNCTION_ALIASES.get(function) or function
    span = find_function(source_text, function_name)
    if span is None and source_function and source_function != function:
        span = find_function(source_text, function)
        function_name = function if span is not None else function_name
    if span is None:
        return {
            "status": "blocked",
            "kind": KIND,
            "function": function,
            "source_function": source_function,
            "reason": f"target function {function_name!r} not found in source",
            "evidence": evidence,
            "candidates": [],
        }

    if not evidence["ready"]:
        return {
            "status": "blocked",
            "kind": KIND,
            "function": function,
            "source_function": function_name,
            "reason": "required post-ceiling terminal evidence is incomplete",
            "evidence": evidence,
            "candidates": [],
        }

    validation_metadata = _validation_metadata(evidence, validation_options or {})
    candidates = _generate_candidate_objects(
        source_text,
        function_name=function_name,
        requested_function=function,
        suppressed_families=set(evidence["suppressed_families"]),
        validation_metadata=validation_metadata,
    )
    if max_candidates >= 0:
        candidates = candidates[:max_candidates]

    score_classification = classify_baseline_escape_scores(
        score_payloads,
        generated_candidate_ids=[candidate.candidate_id for candidate in candidates],
        function=function,
    )
    status = "generated" if candidates else "blocked"
    payload: dict[str, Any] = {
        "status": status,
        "kind": KIND,
        "function": function,
        "source_function": function_name,
        "families": list(dict.fromkeys(candidate.family for candidate in candidates)),
        "candidate_count": len(candidates),
        "evidence": evidence,
        "transform_family_hints": [
            *_transform_family_hints(function=function),
        ],
        "validation_hint": _validation_hint(function=function),
        "candidates": [
            candidate.to_dict(base_source=source_text, include_source=include_source)
            for candidate in candidates
        ],
    }
    if not candidates:
        if _retained_all_supported_baseline_escape_closed(
            function=function,
            evidence=evidence,
        ):
            final_summary = _retained_all_known_terminal_summary(
                function=function,
                source_function=function_name,
                evidence=evidence,
            )
            payload["status"] = "terminal"
            payload["reason"] = FINAL_TERMINAL_REASON
            payload["terminal_summary"] = {
                "status": "terminal",
                "kind": _terminal_kind(function),
                "terminal_blocker": TERMINAL_BLOCKER,
                "terminal_reason": _terminal_reason(function),
                "candidate_count": 0,
                "scored_count": 0,
                "target_anchors": evidence.get("target_anchors", []),
                "final_force_phys": evidence.get("final_force_phys", {}),
                "attempted_targets": evidence.get("final_force_phys", {}),
            }
            payload["post_ceiling_final_summary"] = final_summary
        else:
            payload["reason"] = "no supported post-ceiling source anchors found"
    if score_classification["score_count"]:
        payload["score_classification"] = score_classification
        score_rows = score_classification["candidates"]
        score_force_summary = _score_force_phys_summary(score_rows)
        final_force_phys = _merged_force_phys(
            evidence.get("final_force_phys"),
            score_force_summary["force_phys"],
        )
        if final_force_phys != evidence.get("final_force_phys"):
            evidence = _evidence_with_final_force(evidence, final_force_phys)
            payload["evidence"] = evidence
        if score_force_summary["conflicts"]:
            evidence["score_force_conflicts"] = score_force_summary["conflicts"]
            terminal_summary = (
                score_classification.get("terminal_summary")
                or _terminal_summary(score_rows, function=function)
            )
            terminal_summary["target_anchors"] = evidence.get("target_anchors", [])
            terminal_summary["final_force_phys"] = final_force_phys
            terminal_summary["attempted_targets"] = final_force_phys
            terminal_summary["force_map_conflicts"] = score_force_summary["conflicts"]
            score_classification["terminal_summary"] = terminal_summary
            payload["terminal_summary"] = terminal_summary
            payload["post_ceiling_final_summary"] = (
                _post_ceiling_force_conflict_summary(
                    function=function,
                    source_function=function_name,
                    terminal_summary=terminal_summary,
                    score_rows=score_rows,
                    evidence=evidence,
                    force_conflicts=score_force_summary["conflicts"],
                )
            )
            payload["status"] = "terminal"
        elif score_classification.get("terminal_summary") is not None:
            score_classification["terminal_summary"]["target_anchors"] = (
                evidence.get("target_anchors", [])
            )
            score_classification["terminal_summary"]["final_force_phys"] = (
                final_force_phys
            )
            score_classification["terminal_summary"]["attempted_targets"] = (
                final_force_phys
            )
            if (
                _retained_continuation_terminal_without_routes(evidence)
                or _source_family_scores_close_terminal(function, score_rows)
            ):
                payload["post_ceiling_final_summary"] = (
                    _post_ceiling_final_synthesis_summary(
                        function=function,
                        source_function=function_name,
                        terminal_summary=score_classification["terminal_summary"],
                        score_rows=score_rows,
                        evidence=evidence,
                        force_conflicts=score_force_summary["conflicts"],
                        source_text=source_text,
                        generated_candidates=payload["candidates"],
                        validation_options=validation_options or {},
                        include_source=include_source,
                    )
                )
                payload["status"] = "terminal"
            else:
                continuation_summary = analyze_baseline_escape_continuations(
                    source_text,
                    function=function,
                    source_function=function_name,
                    generated_candidates=payload["candidates"],
                    score_rows=score_rows,
                    evidence=evidence,
                    validation_options=validation_options or {},
                )
                if _continuation_routes_closed_by_retained(
                    evidence,
                    continuation_summary,
                ):
                    payload["post_ceiling_final_summary"] = (
                        _post_ceiling_final_synthesis_summary(
                            function=function,
                            source_function=function_name,
                            terminal_summary=score_classification["terminal_summary"],
                            score_rows=score_rows,
                            evidence=evidence,
                            continuation_summary=continuation_summary,
                            source_text=source_text,
                            generated_candidates=payload["candidates"],
                            validation_options=validation_options or {},
                            include_source=include_source,
                        )
                    )
                    payload["status"] = "terminal"
                else:
                    if continuation_summary is not None:
                        payload["post_ceiling_continuation_summary"] = (
                            continuation_summary
                        )
                    payload["status"] = (
                        "actionable"
                        if continuation_summary is not None
                        and continuation_summary.get("status") == "source-actionable"
                        else "terminal"
                    )
            payload["terminal_summary"] = score_classification["terminal_summary"]
        elif score_classification.get("progress_count", 0) > 0:
            plateau_summary = _source_family_progress_plateau_summary(
                function=function,
                score_rows=score_rows,
                final_force_phys=final_force_phys,
            )
            if plateau_summary is not None:
                plateau_summary["target_anchors"] = evidence.get("target_anchors", [])
                terminal_summary = _terminal_summary(score_rows, function=function)
                terminal_summary["target_anchors"] = evidence.get("target_anchors", [])
                terminal_summary["final_force_phys"] = final_force_phys
                terminal_summary["attempted_targets"] = final_force_phys
                terminal_summary["source_family_progress_plateau"] = plateau_summary
                score_classification["terminal_summary"] = terminal_summary
                payload["terminal_summary"] = terminal_summary
                payload["post_ceiling_source_family_plateau_summary"] = (
                    plateau_summary
                )
                payload["post_ceiling_final_summary"] = (
                    _post_ceiling_final_synthesis_summary(
                        function=function,
                        source_function=function_name,
                        terminal_summary=terminal_summary,
                        score_rows=score_rows,
                        evidence=evidence,
                        source_text=source_text,
                        generated_candidates=payload["candidates"],
                        validation_options=validation_options or {},
                        include_source=include_source,
                    )
                )
                payload["status"] = "terminal"
            else:
                payload["status"] = "actionable"
    elif score_payloads:
        payload["score_classification"] = score_classification
    final_summary = payload.get("post_ceiling_final_summary")
    if (
        isinstance(final_summary, Mapping)
        and final_summary.get("kind") == FINAL_TERMINAL_KIND
        and isinstance(
            final_summary.get("post_ceiling_source_family_discovery"),
            Mapping,
        )
    ):
        payload["post_ceiling_source_family_discovery"] = final_summary[
            "post_ceiling_source_family_discovery"
        ]
    return payload


def generate_baseline_escape_candidate_files(
    source_text: str,
    *,
    function: str,
    source_function: str | None = None,
    allocator_ceiling: Mapping[str, Any] | None = None,
    expression_interferer: Mapping[str, Any] | None = None,
    retained_frontiers: Mapping[str, Any] | None = None,
    supplemental_evidence: Sequence[Mapping[str, Any]] = (),
    score_payloads: Sequence[Mapping[str, Any]] = (),
    output_dir: Path,
    max_candidates: int = 12,
    include_source: bool = False,
    validation_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = generate_baseline_escape_candidates(
        source_text,
        function=function,
        source_function=source_function,
        allocator_ceiling=allocator_ceiling,
        expression_interferer=expression_interferer,
        retained_frontiers=retained_frontiers,
        supplemental_evidence=supplemental_evidence,
        score_payloads=score_payloads,
        max_candidates=max_candidates,
        include_source=True,
        validation_options=validation_options,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _retain_candidate_sources(
        payload.get("candidates", []),
        output_dir=output_dir,
        include_source=include_source,
    )
    discovery = payload.get("post_ceiling_source_family_discovery")
    if isinstance(discovery, Mapping):
        _retain_candidate_sources(
            discovery.get("candidates", []),
            output_dir=output_dir / "source-family",
            include_source=include_source,
        )
    payload["output_dir"] = str(output_dir)
    return payload


def _retain_candidate_sources(
    rows: Any,
    *,
    output_dir: Path,
    include_source: bool,
) -> None:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = str(
            row.get("candidate_id") or row.get("probe_id") or "candidate"
        )
        source = row.pop("source_text", None)
        if not isinstance(source, str):
            continue
        path = output_dir / _candidate_source_filename(candidate_id)
        path.write_text(source, encoding="utf-8")
        path_text = str(path)
        row["path"] = path_text
        row["candidate_path"] = path_text
        row["source_retained"] = path_text
        _patch_candidate_path_hints(row, path)
        if include_source:
            row["source_text"] = source


def _candidate_source_filename(candidate_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", candidate_id).strip(".-")
    if not stem:
        stem = "candidate"
    max_stem_bytes = 178
    encoded = stem.encode("utf-8")
    if len(encoded) > max_stem_bytes:
        stem = encoded[:max_stem_bytes].decode("ascii", "ignore").rstrip(".-")
        if not stem:
            stem = "candidate"
    return f"{stem}.c"


def _patch_candidate_path_hints(row: Mapping[str, Any], path: Path) -> None:
    metadata = row.get("validation_metadata")
    if not isinstance(metadata, dict):
        return
    hint = metadata.get("score_source_command_hint")
    if not isinstance(hint, str):
        return
    metadata["score_source_command_hint"] = hint.replace(
        "{candidate_path}",
        shlex.quote(str(path)),
    )


def classify_baseline_escape_scores(
    score_payloads: Sequence[Mapping[str, Any]],
    *,
    generated_candidate_ids: Sequence[str] = (),
    function: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, score_payload in enumerate(score_payloads):
        row = _classify_score_payload(score_payload, index=index)
        rows.append(row)

    progress_rows = [
        row
        for row in rows
        if row["classification"] in {"expression-progress", "target-progress"}
    ]
    generated = set(generated_candidate_ids)
    scored_ids = {str(row["candidate_id"]) for row in rows if row.get("candidate_id")}
    all_generated_scored = bool(generated) and generated <= scored_ids
    terminal = None
    if rows and all_generated_scored and not progress_rows:
        terminal = _terminal_summary(rows, function=function)

    best = _best_score_row(rows)
    return {
        "score_count": len(rows),
        "progress_count": len(progress_rows),
        "all_generated_scored": all_generated_scored,
        "best_expression_matched": (
            best.get("expression_matched") if best is not None else None
        ),
        "best_expression_targeted": (
            best.get("expression_targeted") if best is not None else None
        ),
        "best_target_matched": (
            best.get("target_matched") if best is not None else None
        ),
        "best_target_targeted": (
            best.get("target_targeted") if best is not None else None
        ),
        "best_candidate_id": best.get("candidate_id") if best is not None else None,
        "candidates": rows,
        "terminal_summary": terminal,
    }


def _source_family_scores_close_terminal(
    function: str,
    score_rows: Sequence[Mapping[str, Any]],
) -> bool:
    expected = _expected_source_family_candidate_ids(function)
    if not expected:
        return False
    scored = {
        str(row.get("candidate_id"))
        for row in score_rows
        if isinstance(row, Mapping) and row.get("candidate_id") is not None
    }
    return expected <= scored


def _expected_source_family_candidate_ids(function: str) -> set[str]:
    return {
        f"post-ceiling-source-family-{spec['dimension_id']}"
        for spec in _source_family_dimension_specs(function)
    }


def _source_family_progress_plateau_summary(
    *,
    function: str,
    score_rows: Sequence[Mapping[str, Any]],
    final_force_phys: Mapping[str, int],
) -> dict[str, Any] | None:
    expected = _expected_source_family_candidate_ids(function)
    if not expected:
        return None
    source_rows = [
        row
        for row in score_rows
        if (
            isinstance(row, Mapping)
            and str(row.get("candidate_id") or "") in expected
        )
    ]
    scored_source_ids = {
        str(row.get("candidate_id"))
        for row in source_rows
        if row.get("candidate_id") is not None
    }
    if not expected <= scored_source_ids:
        return None
    all_progress_rows = [
        row
        for row in score_rows
        if (
            isinstance(row, Mapping)
            and row.get("classification")
            in {"expression-progress", "target-progress"}
        )
    ]
    progress_rows = [
        row
        for row in source_rows
        if row.get("classification") in {"expression-progress", "target-progress"}
    ]
    if not progress_rows:
        return None
    if len(progress_rows) != len(all_progress_rows):
        return None
    if any(_score_row_is_exact(row) for row in source_rows):
        return None
    best = _best_score_row(source_rows) or _best_score_row(score_rows)
    best_rows = [best] if isinstance(best, Mapping) else []
    return {
        "status": "terminal",
        "kind": SOURCE_FAMILY_PROGRESS_TERMINAL_KIND,
        "terminal_blocker": TERMINAL_BLOCKER,
        "terminal_reason": SOURCE_FAMILY_PROGRESS_TERMINAL_REASON,
        "family_id": SOURCE_FAMILY_DISCOVERY_FAMILY,
        "suppression_family": SOURCE_FAMILY_DISCOVERY_FAMILY,
        "candidate_count": len(source_rows),
        "scored_count": len(source_rows),
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_expression_matched": (
            best.get("expression_matched") if best else None
        ),
        "best_expression_targeted": (
            best.get("expression_targeted") if best else None
        ),
        "best_target_matched": best.get("target_matched") if best else None,
        "best_target_targeted": best.get("target_targeted") if best else None,
        "final_force_phys": dict(final_force_phys),
        "attempted_targets": dict(final_force_phys),
        "progress_candidate_ids": [
            str(row.get("candidate_id"))
            for row in progress_rows
            if row.get("candidate_id") is not None
        ],
        "source_family_candidate_ids": sorted(expected),
        "source_family_score_rows": [
            _source_family_score_row_summary(row) for row in source_rows
        ],
        "source_family_residual_blocker_targets": _residual_blocker_targets(
            best_rows,
            final_force_phys,
        ),
        "plateau_reason": (
            "all expected source-family probes were scored, at least one "
            "made partial register-target progress, and none matched all "
            "requested targets"
        ),
    }


def _score_row_is_exact(row: Mapping[str, Any]) -> bool:
    for matched_key, targeted_key in (
        ("target_matched", "target_targeted"),
        ("expression_matched", "expression_targeted"),
    ):
        matched = _int_or_none(row.get(matched_key))
        targeted = _int_or_none(row.get(targeted_key))
        if targeted is not None and targeted > 0 and matched is not None:
            if matched >= targeted:
                return True
    return False


def _source_family_score_row_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        "candidate_id": row.get("candidate_id"),
        "classification": row.get("classification"),
        "source_retained": row.get("source_retained"),
        "pcdump_path": row.get("pcdump_path"),
        "target_matched": row.get("target_matched"),
        "target_targeted": row.get("target_targeted"),
        "target_virtual_distance": row.get("target_virtual_distance"),
        "expression_matched": row.get("expression_matched"),
        "expression_targeted": row.get("expression_targeted"),
        "expression_virtual_distance": row.get("expression_virtual_distance"),
    }
    target_score = row.get("target_score")
    if isinstance(target_score, Mapping):
        virtuals = target_score.get("virtuals")
        if isinstance(virtuals, Mapping):
            out["target_virtuals"] = {
                str(virtual): dict(payload)
                for virtual, payload in virtuals.items()
                if isinstance(payload, Mapping)
            }
    expression_score = row.get("expression_score")
    if isinstance(expression_score, Mapping):
        virtuals = expression_score.get("virtuals")
        if isinstance(virtuals, Mapping):
            out["expression_virtuals"] = {
                str(virtual): dict(payload)
                for virtual, payload in virtuals.items()
                if isinstance(payload, Mapping)
            }
    return out


def analyze_baseline_escape_continuations(
    source_text: str,
    *,
    function: str,
    source_function: str | None,
    generated_candidates: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    validation_options: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Classify post-ceiling scored candidates into second-generation routes."""

    if not score_rows:
        return None
    class_id = _continuation_class_id(function, validation_options or {})
    score_force_summary = _score_force_phys_summary(score_rows)
    final_force = _merged_force_phys(
        evidence.get("final_force_phys"),
        score_force_summary["force_phys"],
    )
    if score_force_summary["conflicts"]:
        return {
            "status": "terminal",
            "kind": FORCE_CONFLICT_TERMINAL_KIND,
            "terminal_blocker": FORCE_CONFLICT_BLOCKER,
            "terminal_reason": FORCE_CONFLICT_TERMINAL_REASON,
            "family_id": CONTINUATION_FAMILY,
            "suppression_family": CONTINUATION_FAMILY,
            "function": function,
            "source_function": source_function,
            "class_id": class_id,
            "final_force_phys": dict(final_force),
            "candidate_count": len(score_rows),
            "scored_count": len(score_rows),
            "force_map_conflicts": score_force_summary["conflicts"],
        }
    generated_by_id = {
        str(row.get("candidate_id")): row
        for row in generated_candidates
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    ranked: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for score_row in score_rows:
        if not isinstance(score_row, Mapping):
            continue
        candidate_id = str(score_row.get("candidate_id") or "")
        generated = generated_by_id.get(candidate_id, {})
        analysis = _analyze_score_row_continuation(
            source_text,
            function=function,
            source_function=source_function,
            class_id=class_id,
            logical_force_phys=final_force,
            score_row=score_row,
            generated_candidate=generated,
        )
        if analysis.get("status") == "source-actionable":
            ranked.append(analysis)
        else:
            blockers.append(analysis)

    if ranked:
        ranked.sort(key=_continuation_rank_key)
        for index, row in enumerate(ranked, start=1):
            row["rank"] = index
        return {
            "status": "source-actionable",
            "kind": CONTINUATION_KIND,
            "family_id": CONTINUATION_FAMILY,
            "suppression_family": CONTINUATION_FAMILY,
            "function": function,
            "source_function": source_function,
            "class_id": class_id,
            "final_force_phys": dict(final_force),
            "ranked_candidates": ranked,
            "blockers": blockers,
        }

    if blockers:
        return {
            "status": "terminal",
            "kind": CONTINUATION_TERMINAL_KIND,
            "terminal_blocker": "all-candidate-routes-unsupported",
            "terminal_reason": CONTINUATION_TERMINAL_REASON,
            "family_id": CONTINUATION_FAMILY,
            "suppression_family": CONTINUATION_FAMILY,
            "function": function,
            "source_function": source_function,
            "class_id": class_id,
            "final_force_phys": dict(final_force),
            "candidate_count": len(score_rows),
            "scored_count": len(score_rows),
            "blockers": blockers,
        }
    return None


def _analyze_score_row_continuation(
    source_text: str,
    *,
    function: str,
    source_function: str | None,
    class_id: int,
    logical_force_phys: Mapping[str, int],
    score_row: Mapping[str, Any],
    generated_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_id = str(score_row.get("candidate_id") or "")
    pcdump_path = _continuation_path(score_row.get("pcdump_path"))
    source_retained = _continuation_source_path(score_row, generated_candidate)
    base: dict[str, Any] = {
        "rank": None,
        "candidate_id": candidate_id,
        "source_retained": str(source_retained) if source_retained is not None else None,
        "pcdump_path": str(pcdump_path) if pcdump_path is not None else None,
        "score_classification": score_row.get("classification"),
        "continuation": None,
    }
    if pcdump_path is None:
        return _continuation_blocker(
            base,
            "retained-pcdump-missing",
            "score row did not include a readable retained pcdump_path",
        )

    candidate_force, force_derivation, force_blockers = _candidate_force_phys(
        score_row,
        logical_force_phys=logical_force_phys,
        class_id=class_id,
    )
    if not candidate_force:
        base["force_derivation"] = force_derivation
        return _continuation_blocker(
            base,
            "candidate-force-map-empty",
            "no candidate virtuals could be mapped from the logical force targets",
            extra={"force_blockers": force_blockers},
        )

    try:
        first_divergence = _first_divergence_for_candidate(
            pcdump_path,
            function=function,
            source_function=source_function,
            class_id=class_id,
            force_phys=candidate_force,
            source_text=(
                source_retained.read_text(encoding="utf-8")
                if source_retained is not None and source_retained.is_file()
                else source_text
            ),
            source_file=str(source_retained) if source_retained is not None else None,
        )
    except (OSError, ValueError, NotImplementedError) as exc:
        base["force_derivation"] = force_derivation
        return _continuation_blocker(
            base,
            "first-divergence-analysis-failed",
            str(exc),
            extra={"logical_force_phys": dict(logical_force_phys),
                   "candidate_force_phys": dict(candidate_force)},
        )

    base["retained_first_divergence"] = first_divergence
    base["force_derivation"] = force_derivation
    base["logical_force_phys"] = dict(logical_force_phys)
    base["candidate_force_phys"] = {
        str(key): value for key, value in candidate_force.items()
    }

    route = _continuation_route(
        function=function,
        class_id=class_id,
        pcdump_path=pcdump_path,
        source_retained=source_retained,
        candidate_force_phys=candidate_force,
        first_divergence=first_divergence,
        suppressed_families=_suppressed_families_from_score(score_row),
    )
    if route is None:
        return _continuation_blocker(
            base,
            "no-source-actionable-route",
            "first-divergence did not yield a supported retained continuation route",
        )
    base["status"] = "source-actionable"
    base["kind"] = route.get("kind")
    base["continuation"] = route
    return base


def _first_divergence_for_candidate(
    pcdump_path: Path,
    *,
    function: str,
    source_function: str | None,
    class_id: int,
    force_phys: Mapping[int, int],
    source_text: str,
    source_file: str | None,
) -> dict[str, Any]:
    from . import first_divergence as fd
    from .colorgraph_parser import find_function, parse_hook_events
    from .parser import parse_pcdump

    text = pcdump_path.read_text(encoding="utf-8", errors="replace")
    events = parse_hook_events(text)
    pcdump_function = _first_existing_function(
        events,
        candidates=(function, source_function),
        finder=find_function,
    )
    if pcdump_function is None:
        raise ValueError(f"function {function!r} not found in retained pcdump")
    fev = find_function(events, pcdump_function)
    report = fd.analyze_first_divergence(
        fev,
        fd.TargetColoring(class_id=class_id, force_phys=force_phys),
    )
    pre = None
    try:
        parsed_function = next(
            (
                parsed
                for parsed in parse_pcdump(text)
                if parsed.name == pcdump_function
            ),
            None,
        )
        if parsed_function is not None:
            pre = parsed_function.last_precolor_pass()
    except Exception:
        pre = None
    source_lookup_function = source_function or function
    source_idea = fd.attach_source_ideas(
        report.fact,
        source_text,
        source_lookup_function,
        pre,
        source_file=source_file,
    )
    payload = fd.report_to_dict(
        fd.FirstDivergenceReport(fact=report.fact, source=source_idea)
    )
    payload["status"] = "ok"
    payload["pcdump_function"] = pcdump_function
    payload["source_lookup_function"] = source_lookup_function
    return payload


def _first_existing_function(events: Any, *, candidates: Sequence[str | None],
                             finder: Any) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        if finder(events, candidate) is not None:
            return candidate
    return None


def _continuation_route(
    *,
    function: str,
    class_id: int,
    pcdump_path: Path,
    source_retained: Path | None,
    candidate_force_phys: Mapping[int, int],
    first_divergence: Mapping[str, Any],
    suppressed_families: set[str],
) -> dict[str, Any] | None:
    fact = _nested_mapping(first_divergence, ("fact",)) or {}
    source = _nested_mapping(first_divergence, ("source",)) or {}
    case = str(fact.get("case") or "")
    if _unsupported_fpr_stack_temp(class_id, source):
        return None
    if source_retained is None or not source_retained.is_file():
        return None
    if case in {"C", "C2"}:
        if "retained-source-select-order-repair" in suppressed_families:
            return None
        target_orders = _select_order_targets_for_case_c(
            fact,
            source,
            candidate_force_phys,
        )
        if not target_orders:
            return None
        target = ",".join(f"r{before}<r{after}" for before, after in target_orders)
        force_csv = _force_phys_csv(candidate_force_phys)
        command = shlex.join([
            "melee-agent",
            "debug",
            "select-order-search",
            "-f",
            function,
            "--class",
            str(class_id),
            "--target",
            target,
            "--pcdump",
            str(pcdump_path),
            "--source-file",
            str(source_retained),
            "--force-phys",
            force_csv,
            "--json",
        ])
        return {
            "route": "retained-source-select-order-repair",
            "kind": "retained-source-select-order-repair",
            "target_orders": [[before, after] for before, after in target_orders],
            "command": command,
            "source_retained": str(source_retained),
            "pcdump_path": str(pcdump_path),
        }
    if case == "D":
        ig_idx = _int_or_none(fact.get("ig_idx"))
        root = _int_or_none(fact.get("coalesced_root"))
        if ig_idx is None or root is None:
            return None
        split_var = _trusted_split_var(class_id, source)
        parts = [
            "melee-agent",
            "debug",
            "coalesce-search",
            "-f",
            function,
            "--target",
            f"r{ig_idx}=r{root}",
            "--pcdump",
            str(pcdump_path),
            "--source-file",
            str(source_retained),
            "--json",
        ]
        if split_var:
            parts.extend(["--split-var", split_var])
        command = shlex.join(parts)
        return {
            "route": "retained-coalesce-search",
            "kind": "retained-coalesce-search",
            "target_pairs": [[ig_idx, root]],
            "split_var": split_var,
            "command": command,
            "source_retained": str(source_retained),
            "pcdump_path": str(pcdump_path),
        }
    return None


def _continuation_blocker(
    base: Mapping[str, Any],
    blocker: str,
    reason: str,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(base)
    out["status"] = "blocked"
    out["blocker"] = blocker
    out["reason"] = reason
    if extra:
        out.update(extra)
    return out


def _continuation_class_id(
    function: str,
    validation_options: Mapping[str, Any],
) -> int:
    explicit = _int_or_none(validation_options.get("class_id"))
    if explicit is not None:
        return explicit
    register_class = str(validation_options.get("register_class") or "").lower()
    if register_class == "fpr":
        return 1
    if register_class == "gpr":
        return 0
    return 0 if _is_sort_profile(function) else 1


def _candidate_force_phys(
    score_row: Mapping[str, Any],
    *,
    logical_force_phys: Mapping[str, int],
    class_id: int,
) -> tuple[dict[int, int], list[dict[str, Any]], list[dict[str, Any]]]:
    if class_id != 1:
        direct = {
            int(key): value
            for key, value in _normalized_int_mapping(logical_force_phys).items()
        }
        return direct, [
            {
                "logical_ig": int(key),
                "candidate_ig": int(key),
                "target_reg": value,
                "source": "logical-force-phys",
            }
            for key, value in sorted(direct.items())
        ], []

    expression_score = _nested_mapping(score_row, ("expression_score",))
    expression_virtuals = (
        expression_score.get("virtuals")
        if isinstance(expression_score, Mapping)
        else None
    )
    target_score = _nested_mapping(score_row, ("target_score",))
    target_virtuals = (
        target_score.get("virtuals") if isinstance(target_score, Mapping) else None
    )
    out: dict[int, int] = {}
    derivation: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for logical_key, target_reg in _normalized_int_mapping(logical_force_phys).items():
        logical_ig = _int_or_none(logical_key)
        if logical_ig is None:
            continue
        expr_row = (
            expression_virtuals.get(str(logical_ig))
            if isinstance(expression_virtuals, Mapping)
            else None
        )
        candidate_ig = (
            _int_or_none(expr_row.get("candidate_virtual"))
            if isinstance(expr_row, Mapping)
            else None
        )
        source = "expression-candidate-virtual"
        if candidate_ig is None and _allow_fpr_logical_fallback(
            logical_ig,
            expr_row,
            target_virtuals,
        ):
            candidate_ig = logical_ig
            source = "pcode-target-score-fallback"
        if candidate_ig is None:
            blockers.append({
                "logical_ig": logical_ig,
                "target_reg": target_reg,
                "blocker": "candidate-virtual-unresolved",
            })
            continue
        out[candidate_ig] = target_reg
        derivation.append({
            "logical_ig": logical_ig,
            "candidate_ig": candidate_ig,
            "target_reg": target_reg,
            "source": source,
        })
    return out, derivation, blockers


def _allow_fpr_logical_fallback(
    logical_ig: int,
    expr_row: Any,
    target_virtuals: Any,
) -> bool:
    if isinstance(expr_row, Mapping):
        for key in ("candidate_source", "baseline_source", "signature"):
            raw = expr_row.get(key)
            if isinstance(raw, Mapping):
                source_kind = str(raw.get("source_kind") or raw.get("kind") or "")
                if "fpr-temp" in source_kind or raw.get("kind") == "first-def":
                    return True
    target_row = (
        target_virtuals.get(str(logical_ig))
        if isinstance(target_virtuals, Mapping)
        else None
    )
    if isinstance(target_row, Mapping) and _int_or_none(target_row.get("actual")) is not None:
        return True
    return False


def _continuation_path(raw: Any) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve() if path.is_file() else None


def _continuation_source_path(
    score_row: Mapping[str, Any],
    generated_candidate: Mapping[str, Any],
) -> Path | None:
    for raw in (
        generated_candidate.get("source_retained"),
        generated_candidate.get("path"),
        score_row.get("source_retained"),
        score_row.get("source_file"),
        score_row.get("path"),
    ):
        path = _continuation_path(raw)
        if path is not None and path.suffix == ".c":
            return path
    pcdump = score_row.get("pcdump_path")
    if isinstance(pcdump, str) and pcdump.endswith(".pcdump.txt"):
        return _continuation_path(pcdump[: -len(".pcdump.txt")] + ".c")
    return None


def _continuation_rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    route = row.get("continuation")
    route_name = route.get("route") if isinstance(route, Mapping) else ""
    class_rank = {
        "retained-source-select-order-repair": 0,
        "retained-coalesce-search": 1,
    }.get(str(route_name), 9)
    classification_rank = {
        "structural-preserving": 0,
        "recoverable-downhill": 1,
        "unscoreable": 2,
    }.get(str(row.get("score_classification")), 3)
    return (class_rank, classification_rank, str(row.get("candidate_id") or ""))


def _select_order_targets_for_case_c(
    fact: Mapping[str, Any],
    source: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> list[tuple[int, int]]:
    target_ig = _int_or_none(fact.get("ig_idx"))
    if target_ig is None:
        return []
    peer_igs = [ig for ig in force_phys if ig != target_ig]
    if not peer_igs:
        return []
    operands = set(_virtual_operands_from_source(source))
    peer_igs.sort(key=lambda ig: (0 if ig in operands else 1, ig))
    return [(peer_igs[0], target_ig)]


def _virtual_operands_from_source(source: Mapping[str, Any]) -> list[int]:
    haystack = " ".join(
        str(source.get(key) or "")
        for key in ("first_def", "source_expression", "blocker_first_def")
    )
    out: list[int] = []
    for match in re.finditer(r"\b[rf](\d+)\b", haystack):
        parsed = _int_or_none(match.group(1))
        if parsed is not None and parsed not in out:
            out.append(parsed)
    return out


def _unsupported_fpr_stack_temp(class_id: int, source: Mapping[str, Any]) -> bool:
    if class_id != 1:
        return False
    source_kind = str(source.get("source_kind") or "")
    expression = str(source.get("source_expression") or source.get("first_def") or "")
    return (
        source_kind in {"fpr-temp", "implicit-temp"}
        and bool(re.search(r"\b[ls]fd\b|@", expression))
        and not source.get("candidate_spans")
    )


def _trusted_split_var(class_id: int, source: Mapping[str, Any]) -> str | None:
    var_name = source.get("var_name")
    if not isinstance(var_name, str) or not var_name:
        return None
    if class_id == 1 and _looks_gpr_source_name(var_name):
        return None
    confidence = str(source.get("source_confidence") or source.get("confidence") or "")
    if confidence in {"", "best-guess", "weak"}:
        return None
    return var_name


def _looks_gpr_source_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in {"gobj", "jobj", "assets", "fighter", "file", "data"}
        or lowered.endswith("_ptr")
        or lowered.endswith("ptr")
    )


def _force_phys_csv(force_phys: Mapping[int, int]) -> str:
    return ",".join(
        f"{key}:{force_phys[key]}" for key in sorted(force_phys)
    )


def _normalized_int_mapping(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        parsed_key = _int_or_none(key)
        parsed_value = _int_or_none(value)
        if parsed_key is not None and parsed_value is not None:
            out[str(parsed_key)] = parsed_value
    return out


def _suppressed_families_from_score(score_row: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for raw in (
        score_row.get("suppressed_families"),
        _nested_get(score_row, ("validation_metadata", "suppressed_families")),
    ):
        out.update(_string_items(raw))
    return out


def _generate_candidate_objects(
    source_text: str,
    *,
    function_name: str,
    requested_function: str,
    suppressed_families: set[str],
    validation_metadata: Mapping[str, Any],
) -> list[BaselineEscapeCandidate]:
    span = find_function(source_text, function_name)
    if span is None:
        return []
    function_text = source_text[span.sig_start:span.full_end]
    candidates: list[BaselineEscapeCandidate] = []
    seen: set[str] = set()

    def add(
        *,
        candidate_id: str,
        family: str,
        strategy: str,
        priority: int,
        rationale: str,
        expected_effect: str,
        novelty_reason: str,
        patched_function: str | None,
    ) -> None:
        if family in suppressed_families:
            return
        if patched_function is None or patched_function == function_text:
            return
        patched_source = (
            source_text[:span.sig_start] + patched_function + source_text[span.full_end:]
        )
        if patched_source in seen:
            return
        seen.add(patched_source)
        candidates.append(
            BaselineEscapeCandidate(
                candidate_id=candidate_id,
                family=family,
                strategy=strategy,
                priority=priority,
                rationale=rationale,
                expected_effect=expected_effect,
                novelty_reason=novelty_reason,
                source_text=patched_source,
                validation_metadata=validation_metadata,
            )
        )

    if _is_sort_profile(requested_function):
        _add_sort_candidates(add, function_text)
    else:
        _add_draw_candidates(add, function_text)

    return sorted(candidates, key=lambda candidate: (-candidate.priority, candidate.candidate_id))


def _add_draw_candidates(add: Any, function_text: str) -> None:
    add(
        candidate_id="post-ceiling-paired-offset-block",
        family="post_ceiling_statement_grouping",
        strategy="paired-offset-block",
        priority=100,
        rationale=(
            "Group the column and row offset computations together with "
            "paired source-visible owners instead of changing one exhausted "
            "row/product owner at a time."
        ),
        expected_effect=(
            "alter the row/column FPR lifetime boundary as a coherent baseline"
        ),
        novelty_reason=(
            "paired statement grouping after known row/product and support-order "
            "families reached a terminal"
        ),
        patched_function=_patch_paired_offset_block(function_text),
    )
    add(
        candidate_id="post-ceiling-paired-visible-owner",
        family="post_ceiling_paired_owner_baseline",
        strategy="paired-visible-owner",
        priority=90,
        rationale=(
            "Materialize paired row and column owner copies after the current "
            "offset expressions so both sides cross the same source boundary."
        ),
        expected_effect=(
            "test a broader paired ownership baseline that may initially go "
            "downhill but preserves recoverable source hunks"
        ),
        novelty_reason=(
            "moves both row and column visible owners together, avoiding single "
            "sink-owner/product-owner retries"
        ),
        patched_function=_patch_paired_visible_owner(function_text),
    )
    add(
        candidate_id="post-ceiling-digit-anim-callarg-block",
        family="post_ceiling_call_temp_materialization",
        strategy="digit-anim-callarg-block",
        priority=80,
        rationale=(
            "Materialize the digit animation call argument in a scoped block "
            "around HSD_JObjReqAnimAll instead of moving product or row offset "
            "statements around mn_GetDigitCount."
        ),
        expected_effect=(
            "test helper-call argument pressure near the digit animation FPR "
            "anchor using a bounded source baseline"
        ),
        novelty_reason=(
            "targets the digit-call FPR anchor and points broader callarg "
            "exploration at existing transform-corpus families"
        ),
        patched_function=_patch_digit_anim_callarg_block(function_text),
    )


def _add_sort_candidates(add: Any, function_text: str) -> None:
    add(
        candidate_id="post-ceiling-sort-address-value-pair",
        family="post_ceiling_sort_address_value_pair",
        strategy="sorted-name-address-value-pair",
        priority=100,
        rationale=(
            "Materialize max_idx and j sorted-name address/value ownership "
            "together before the comparison instead of retrying local "
            "indexed-byte owner order."
        ),
        expected_effect=(
            "change the implicit add/copy product around IG34/IG44 while "
            "preserving a coherent selection-sort baseline"
        ),
        novelty_reason=(
            "pairs both address and value sides after indexed-byte and "
            "residual Case-C single-owner lanes exhausted"
        ),
        patched_function=_patch_sort_address_value_pair(function_text),
    )
    add(
        candidate_id="post-ceiling-sort-init-pointer-walk",
        family="post_ceiling_sort_loop_shape",
        strategy="init-pointer-walk",
        priority=90,
        rationale=(
            "Rewrite the initialization loop as explicit pointer progression "
            "inside the loop body to test a broader loop/source-shape baseline."
        ),
        expected_effect=(
            "move dst_iter/tp lifetime products without changing the sorted "
            "name initialization semantics"
        ),
        novelty_reason=(
            "escapes the exhausted dst_iter pointer-reset lane with a whole-loop "
            "source shape rather than a local reset probe"
        ),
        patched_function=_patch_sort_init_pointer_walk(function_text),
    )
    add(
        candidate_id="post-ceiling-sort-swap-materialization",
        family="post_ceiling_sort_swap_materialization",
        strategy="selected-slot-materialization",
        priority=80,
        rationale=(
            "Materialize the selected name slot before the insertion move so "
            "the address and copied value share a new source boundary."
        ),
        expected_effect=(
            "test a recoverable source-shape delta around the copy-survived "
            "IG34/IG41 path and the IG44 address product"
        ),
        novelty_reason=(
            "changes the selected-slot baseline after copy-survived pointer "
            "reset probes reached a terminal"
        ),
        patched_function=_patch_sort_swap_materialization(function_text),
    )


def _patch_paired_offset_block(function_text: str) -> str | None:
    pattern = re.compile(
        r"(?P<indent>[ \t]*)col_offset\s*=\s*y_spacing\s*\*\s*\(f32\)\s*col\s*;\s*\n"
        r"(?P=indent)rowf\s*=\s*\(f32\)\s*row\s*;\s*\n"
        r"(?P=indent)row_offset\s*\*=\s*rowf\s*;\s*\n"
        r"(?P=indent)row_offset_adj\s*=\s*row_offset\s*-\s*0\.4f\s*;",
        re.MULTILINE,
    )
    match = pattern.search(function_text)
    if match is None:
        return None
    indent = match.group("indent")
    replacement = (
        f"{indent}{{\n"
        f"{indent}    f32 post_ceiling_col_owner;\n"
        f"{indent}    f32 post_ceiling_row_owner;\n"
        f"{indent}    col_offset = y_spacing * (f32) col;\n"
        f"{indent}    rowf = (f32) row;\n"
        f"{indent}    post_ceiling_col_owner = col_offset;\n"
        f"{indent}    post_ceiling_row_owner = row_offset * rowf;\n"
        f"{indent}    col_offset = post_ceiling_col_owner;\n"
        f"{indent}    row_offset = post_ceiling_row_owner;\n"
        f"{indent}    row_offset_adj = row_offset - 0.4f;\n"
        f"{indent}}}"
    )
    return function_text[:match.start()] + replacement + function_text[match.end():]


def _patch_paired_visible_owner(function_text: str) -> str | None:
    pattern = re.compile(
        r"(?P<block>"
        r"(?P<indent>[ \t]*)col_offset\s*=\s*y_spacing\s*\*\s*\(f32\)\s*col\s*;\s*\n"
        r"(?P=indent)rowf\s*=\s*\(f32\)\s*row\s*;\s*\n"
        r"(?P=indent)row_offset\s*\*=\s*rowf\s*;\s*\n"
        r"(?P=indent)row_offset_adj\s*=\s*row_offset\s*-\s*0\.4f\s*;)",
        re.MULTILINE,
    )
    match = pattern.search(function_text)
    if match is None:
        return None
    indent = match.group("indent")
    insertion = (
        f"\n{indent}{{\n"
        f"{indent}    f32 post_ceiling_col_visible;\n"
        f"{indent}    f32 post_ceiling_row_visible;\n"
        f"{indent}    post_ceiling_col_visible = col_offset;\n"
        f"{indent}    post_ceiling_row_visible = row_offset;\n"
        f"{indent}    col_offset = post_ceiling_col_visible;\n"
        f"{indent}    row_offset = post_ceiling_row_visible;\n"
        f"{indent}}}"
    )
    return (
        function_text[:match.end()]
        + insertion
        + function_text[match.end():]
    )


def _patch_digit_anim_callarg_block(function_text: str) -> str | None:
    pattern = re.compile(
        r"(?P<indent>[ \t]*)base\s*=\s*\(f32\)\s*digit\s*;\s*\n"
        r"(?P=indent)HSD_JObjReqAnimAll\(\s*jobj\s*,\s*base\s*\)\s*;",
        re.MULTILINE,
    )
    match = pattern.search(function_text)
    if match is None:
        return None
    indent = match.group("indent")
    replacement = (
        f"{indent}{{\n"
        f"{indent}    f32 post_ceiling_digit_anim_arg;\n"
        f"{indent}    post_ceiling_digit_anim_arg = (f32) digit;\n"
        f"{indent}    base = post_ceiling_digit_anim_arg;\n"
        f"{indent}    HSD_JObjReqAnimAll(jobj, post_ceiling_digit_anim_arg);\n"
        f"{indent}}}"
    )
    return function_text[:match.start()] + replacement + function_text[match.end():]


def _patch_sort_address_value_pair(function_text: str) -> str | None:
    pattern = re.compile(
        r"(?P<indent>[ \t]*)if \(\(GetNameText\(mnDiagram_804A076C\.sorted_names\[j\]\) != NULL\) &&\n"
        r"(?P=indent)[ \t]*\(\(totals\[mnDiagram_804A076C\.sorted_names\[max_idx\]\] <\n"
        r"(?P=indent)[ \t]*totals\[mnDiagram_804A076C\.sorted_names\[j\]\]\) \|\|\n"
        r"(?P=indent)[ \t]*\(\(GetNameText\(\n"
        r"(?P=indent)[ \t]*\(0, mnDiagram_804A076C\.sorted_names\[max_idx\]\)\) ==\n"
        r"(?P=indent)[ \t]*NULL\) &&\n"
        r"(?P=indent)[ \t]*\(GetNameText\(mnDiagram_804A076C\.sorted_names\[j\]\) != NULL\)\)\)\)\n"
        r"(?P=indent)\{\n"
        r"(?P=indent)[ \t]*max_idx = j;\n"
        r"(?P=indent)\}",
        re.MULTILINE,
    )
    match = pattern.search(function_text)
    if match is None:
        return None
    indent = match.group("indent")
    replacement = (
        f"{indent}{{\n"
        f"{indent}    u8* post_ceiling_max_name_slot;\n"
        f"{indent}    u8* post_ceiling_j_name_slot;\n"
        f"{indent}    u8 post_ceiling_max_name;\n"
        f"{indent}    u8 post_ceiling_j_name;\n"
        f"{indent}    post_ceiling_max_name_slot = &mnDiagram_804A076C.sorted_names[max_idx];\n"
        f"{indent}    post_ceiling_j_name_slot = &mnDiagram_804A076C.sorted_names[j];\n"
        f"{indent}    post_ceiling_max_name = *post_ceiling_max_name_slot;\n"
        f"{indent}    post_ceiling_j_name = *post_ceiling_j_name_slot;\n"
        f"{indent}    if ((GetNameText(post_ceiling_j_name) != NULL) &&\n"
        f"{indent}        ((totals[post_ceiling_max_name] < totals[post_ceiling_j_name]) ||\n"
        f"{indent}         ((GetNameText((0, post_ceiling_max_name)) == NULL) &&\n"
        f"{indent}          (GetNameText(post_ceiling_j_name) != NULL))))\n"
        f"{indent}    {{\n"
        f"{indent}        max_idx = j;\n"
        f"{indent}    }}\n"
        f"{indent}}}"
    )
    return function_text[:match.start()] + replacement + function_text[match.end():]


def _patch_sort_init_pointer_walk(function_text: str) -> str | None:
    pattern = re.compile(
        r"(?P<indent>[ \t]*)for \(n = 0; n < 0x78; n\+\+, dst_iter\+\+, tp\+\+\) \{\n"
        r"(?P=indent)[ \t]*\*dst_iter = \(u8\) n;\n"
        r"(?P=indent)[ \t]*\*tp = mnDiagram_SumNameKOs\(n & 0xFF\);\n"
        r"(?P=indent)\}",
        re.MULTILINE,
    )
    match = pattern.search(function_text)
    if match is None:
        return None
    indent = match.group("indent")
    replacement = (
        f"{indent}for (n = 0; n < 0x78; n++) {{\n"
        f"{indent}    *dst_iter = (u8) n;\n"
        f"{indent}    *tp = mnDiagram_SumNameKOs(n & 0xFF);\n"
        f"{indent}    dst_iter++;\n"
        f"{indent}    tp++;\n"
        f"{indent}}}"
    )
    return function_text[:match.start()] + replacement + function_text[match.end():]


def _patch_sort_swap_materialization(function_text: str) -> str | None:
    pattern = re.compile(
        r"(?P<indent>[ \t]*)u8\* p = &assets->sorted_fighters\[max_idx\];\n"
        r"(?P=indent)u8 temp = \*\(p \+= sizeof\(mnDiagram_804A0750_t\)\);",
        re.MULTILINE,
    )
    match = pattern.search(function_text)
    if match is None:
        return None
    indent = match.group("indent")
    replacement = (
        f"{indent}u8* p = &assets->sorted_fighters[max_idx];\n"
        f"{indent}u8* post_ceiling_selected_name_slot = p + sizeof(mnDiagram_804A0750_t);\n"
        f"{indent}u8 temp = *post_ceiling_selected_name_slot;\n"
        f"{indent}p = post_ceiling_selected_name_slot;"
    )
    return function_text[:match.start()] + replacement + function_text[match.end():]


def _normalize_evidence(
    *,
    function: str,
    allocator_ceiling: Mapping[str, Any] | None,
    expression_interferer: Mapping[str, Any] | None,
    retained_frontiers: Mapping[str, Any] | None,
    supplemental_evidence: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    missing: list[str] = []
    sort_profile = _is_sort_profile(function)
    retained_current_source_shape = (
        _retained_frontiers_current_source_shape_ceiling(
            retained_frontiers,
            function=function,
        )
        if sort_profile
        else False
    )
    expected_terminal_reason = (
        _SORT_ALLOCATOR_TERMINAL_REASONS
        if sort_profile
        else _DRAW_ALLOCATOR_TERMINAL_REASON
    )
    allocator_reason = (
        allocator_ceiling.get("terminal_reason")
        if isinstance(allocator_ceiling, Mapping)
        else None
    )
    retained_sort_path = (
        sort_profile
        and allocator_reason == _SORT_ALLOCATOR_RETAINED_TERMINAL_REASON
        and retained_current_source_shape
    )
    allocator_ok = (
        isinstance(allocator_ceiling, Mapping)
        and allocator_ceiling.get("function") == function
        and allocator_ceiling.get("status") == "practical-ceiling"
        and (
            (
                sort_profile
                and allocator_reason in expected_terminal_reason
                and (
                    allocator_reason != _SORT_ALLOCATOR_RETAINED_TERMINAL_REASON
                    or retained_current_source_shape
                )
            )
            or (
                not sort_profile
                and allocator_reason == expected_terminal_reason
            )
        )
    )
    if not allocator_ok:
        missing.append(
            "allocator-ceiling-residual-case-c-terminal"
            if sort_profile
            else "allocator-ceiling-expression-terminal"
        )

    expression_terminal = _expression_terminal(expression_interferer)
    if not sort_profile and expression_terminal is None:
        missing.append("expression-interferer-post-bridge-terminal")
    supplemental_summary = _supplemental_evidence_summary(
        supplemental_evidence,
        function=function,
    )
    legacy_sort_path = (
        sort_profile
        and allocator_reason == _SORT_ALLOCATOR_LEGACY_TERMINAL_REASON
    )
    if sort_profile and not retained_sort_path:
        for required_kind in ("select-order", "node-set", "coalesce"):
            if required_kind not in supplemental_summary["kinds"]:
                missing.append(f"{required_kind}-evidence")

    retained_summary = _retained_frontiers_summary(
        retained_frontiers,
        function=function,
    )
    retained_source_model_proof = _retained_source_model_proof_summary(
        retained_frontiers,
        function=function,
    )
    retained_ok = _retained_frontiers_exhausted(retained_frontiers, function=function)
    if not retained_ok:
        missing.append("retained-frontiers-all-known-exhausted")

    expression_score = _best_expression_score(expression_interferer)
    target_anchors = _expression_targets(expression_score)
    final_force_phys = _target_score_force_phys(expression_interferer)
    for payload in supplemental_evidence:
        final_force_phys.update(_force_phys_from_payload(payload))
    if sort_profile and not target_anchors:
        target_anchors = _target_anchors_from_force_phys(final_force_phys)
    if not final_force_phys:
        final_force_phys = {
            str(anchor["baseline_virtual"]): anchor["expected"]
            for anchor in target_anchors
            if anchor.get("baseline_virtual") is not None
            and anchor.get("expected") is not None
        }
    if not target_anchors and function == "mnDiagram_DrawCellNumber":
        target_anchors = [
            {
                "virtual": 37,
                "baseline_virtual": 37,
                "name": "row_offset",
                "expression": None,
                "expected": 26,
                "actual": 28,
                "matched": False,
            },
            {
                "virtual": 32,
                "baseline_virtual": 32,
                "name": "col_offset",
                "expression": None,
                "expected": 28,
                "actual": 26,
                "matched": False,
            },
            {
                "virtual": 46,
                "baseline_virtual": 46,
                "name": "digit_call_fpr",
                "expression": None,
                "expected": 26,
                "actual": None,
                "matched": False,
            },
        ]
        final_force_phys = {"37": 26, "32": 28, "46": 26}
    suppressed = set(_SUPPRESSED_FAMILY_KEYS)
    if sort_profile:
        suppressed.update(_SORT_SUPPRESSED_FAMILY_KEYS)
    if retained_sort_path:
        suppressed.update(_retained_closed_baseline_escape_families(
            retained_source_model_proof,
        ))
    elif sort_profile and not legacy_sort_path:
        missing.append("retained-frontiers-current-source-shape-ceiling")
    if expression_terminal is not None:
        suppressed.update(_string_items(expression_terminal.get("attempted_families")))
        source_generation = expression_terminal.get("source_generation")
        if isinstance(source_generation, Mapping):
            suppressed.update(_string_items(source_generation.get("suppressed_families")))
    if isinstance(allocator_ceiling, Mapping):
        terminal = allocator_ceiling.get("expression_interferer_terminal")
        if isinstance(terminal, Mapping):
            suppressed.update(_string_items(terminal.get("attempted_families")))
            source_generation = terminal.get("source_generation")
            if isinstance(source_generation, Mapping):
                suppressed.update(_string_items(source_generation.get("suppressed_families")))

    return {
        "ready": not missing,
        "missing_evidence": missing,
        "allocator_ceiling": {
            "status": allocator_ceiling.get("status") if isinstance(allocator_ceiling, Mapping) else None,
            "terminal_reason": allocator_ceiling.get("terminal_reason") if isinstance(allocator_ceiling, Mapping) else None,
        },
        "expression_interferer": {
            "status": expression_interferer.get("status") if isinstance(expression_interferer, Mapping) else None,
            "kind": expression_interferer.get("kind") if isinstance(expression_interferer, Mapping) else None,
            "terminal_kind": expression_terminal.get("kind") if expression_terminal else None,
            "terminal_blocker": expression_terminal.get("terminal_blocker") if expression_terminal else None,
        },
        "supplemental_evidence": supplemental_summary,
        "retained_frontiers": {
            **retained_summary,
        },
        "retained_source_model_proof": retained_source_model_proof,
        "target_anchors": target_anchors,
        "attempted_targets": final_force_phys,
        "final_force_phys": final_force_phys,
        "suppressed_families": sorted(suppressed),
    }


def _expression_terminal(
    expression_interferer: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(expression_interferer, Mapping):
        return None
    terminal = expression_interferer.get("post_bridge_terminal_summary")
    if isinstance(terminal, Mapping) and terminal.get("kind") == _EXPRESSION_TERMINAL_KIND:
        return terminal
    if expression_interferer.get("kind") == _EXPRESSION_TERMINAL_KIND:
        return expression_interferer
    return None


def _is_sort_profile(function: str | None) -> bool:
    return function == _SORT_FUNCTION


def _terminal_kind(function: str | None) -> str:
    return SORT_TERMINAL_KIND if _is_sort_profile(function) else DRAW_TERMINAL_KIND


def _terminal_reason(function: str | None) -> str:
    return f"{_terminal_kind(function)}/{TERMINAL_BLOCKER}"


def _transform_family_hints(*, function: str) -> list[str]:
    if _is_sort_profile(function):
        return [
            "post_ceiling_sort_address_value_pair",
            "post_ceiling_sort_loop_shape",
            "post_ceiling_sort_swap_materialization",
        ]
    return [
        "pcode_only_fpr_callarg_temp_repair",
        "callarg_local_structural_repair",
    ]


def _supplemental_evidence_summary(
    payloads: Sequence[Mapping[str, Any]],
    *,
    function: str,
) -> dict[str, Any]:
    kinds: list[str] = []
    summaries: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        kind = _supplemental_evidence_kind(payload)
        if kind is None:
            continue
        if payload.get("function") not in {None, function}:
            continue
        kinds.append(kind)
        summaries.append(
            {
                "kind": kind,
                "status": payload.get("status"),
                "terminal_reason": payload.get("terminal_reason"),
                "stop_reason": payload.get("stop_reason"),
                "blocked_reason": payload.get("blocked_reason"),
            }
        )
    return {
        "count": len(summaries),
        "kinds": sorted(set(kinds)),
        "artifacts": summaries,
    }


def _supplemental_evidence_kind(payload: Mapping[str, Any]) -> str | None:
    if "window_order_probe_diagnostics" in payload or "terminal_exhaustion_summary" in payload:
        return "select-order"
    if payload.get("stop_reason") == "no-coupled-probes" or "in_place_recolor" in payload:
        return "node-set"
    if "copy_survived_repair" in payload or "trace_copy" in payload:
        return "coalesce"
    if "force_phys" in payload or "virtuals" in payload or "target_spec" in payload:
        return "target"
    return None


def _retained_frontiers_exhausted(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    function: str,
) -> bool:
    if not isinstance(retained_frontiers, Mapping):
        return False
    if retained_frontiers.get("status") != _RETAINED_EXHAUSTED_STATUS:
        return False
    functions = retained_frontiers.get("functions")
    if not isinstance(functions, Sequence) or isinstance(functions, (str, bytes)):
        return True
    for entry in functions:
        if isinstance(entry, Mapping) and entry.get("function") == function:
            return entry.get("next_frontier") is None
    return False


def _retained_frontiers_current_source_shape_ceiling(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    function: str,
) -> bool:
    if not _retained_frontiers_exhausted(retained_frontiers, function=function):
        return False
    entry = _retained_function_entry(retained_frontiers, function=function)
    if entry is None or entry.get("next_frontier") is not None:
        return False
    meta = _retained_meta_ceiling(retained_frontiers, entry=entry, function=function)
    if not isinstance(meta, Mapping):
        return False
    if meta.get("status") != "terminal-current-source-shape-ceiling":
        if (
            meta.get("terminal_reason")
            != _SORT_ALLOCATOR_RETAINED_TERMINAL_REASON
        ):
            return False
    proof = meta.get("terminal_proof")
    if not isinstance(proof, Mapping):
        return False
    return _retained_source_model_proof_concrete(proof)


def _retained_meta_ceiling(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    entry: Mapping[str, Any],
    function: str,
) -> Mapping[str, Any] | None:
    meta = entry.get("meta_ceiling")
    if isinstance(meta, Mapping):
        return meta
    if isinstance(retained_frontiers, Mapping):
        meta = retained_frontiers.get("meta_ceiling")
        if isinstance(meta, Mapping):
            if meta.get("function") in (None, function):
                return meta
        if isinstance(meta, Sequence) and not isinstance(meta, (str, bytes)):
            for item in meta:
                if isinstance(item, Mapping) and item.get("function") == function:
                    return item
    return None


def _retained_source_model_proof_concrete(proof: Mapping[str, Any]) -> bool:
    if _string_or_none(proof.get("next_unsupported_source_model")):
        return True
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        exhausted = synthesis.get("exhausted_dimensions")
        if isinstance(exhausted, Sequence) and not isinstance(exhausted, (str, bytes)):
            if any(isinstance(row, Mapping) for row in exhausted):
                return True
    for key in ("source_spans", "unmapped_source_spans", "candidate_scores"):
        rows = proof.get(key)
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) and rows:
            return True
    return False


def _retained_source_model_proof_summary(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    function: str,
) -> dict[str, Any]:
    entry = _retained_function_entry(retained_frontiers, function=function)
    if entry is None:
        return {}
    meta = _retained_meta_ceiling(retained_frontiers, entry=entry, function=function)
    if not isinstance(meta, Mapping):
        return {}
    proof = meta.get("terminal_proof")
    if not isinstance(proof, Mapping):
        return {}
    synthesis = proof.get("source_family_synthesis")
    current_ceiling = _retained_current_ceiling(
        retained_frontiers,
        entry=entry,
        meta=meta,
        function=function,
    )
    exhausted_dimensions: list[dict[str, Any]] = []
    source_hunks: list[dict[str, Any]] = []
    if isinstance(synthesis, Mapping):
        exhausted_dimensions = [
            dict(row)
            for row in synthesis.get("exhausted_dimensions") or []
            if isinstance(row, Mapping)
        ]
        source_hunks = [
            dict(row)
            for row in synthesis.get("source_hunks_by_candidate") or []
            if isinstance(row, Mapping)
        ]
    summary: dict[str, Any] = {
        "status": proof.get("status"),
        "reason": proof.get("reason"),
        "next_unsupported_source_model": _first_present_mapping_value(
            "next_unsupported_source_model",
            proof,
            synthesis,
            current_ceiling,
        ),
        "next_unsupported_source_family": _first_present_mapping_value(
            "next_unsupported_source_family",
            proof,
            synthesis,
            current_ceiling,
        ),
        "exhausted_dimensions": exhausted_dimensions,
        "source_spans": [
            dict(row)
            for row in proof.get("source_spans") or []
            if isinstance(row, Mapping)
        ],
        "source_hunks_by_candidate": source_hunks,
    }
    for key in ("closed_families", "suppressed_families", "candidate_scores"):
        value = proof.get(key)
        if value is not None:
            summary[key] = value
    if isinstance(synthesis, Mapping):
        summary["source_family_synthesis"] = dict(synthesis)
    return summary


def _retained_frontiers_summary(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    function: str,
) -> dict[str, Any]:
    status = (
        retained_frontiers.get("status")
        if isinstance(retained_frontiers, Mapping)
        else None
    )
    summary: dict[str, Any] = {
        "status": status,
        "function": function,
        "next_frontier_present": False,
        "closed_families": [],
        "terminal_frontiers": [],
        "residual_frontiers": [],
    }
    entry = _retained_function_entry(retained_frontiers, function=function)
    if entry is None:
        return summary

    next_frontier = entry.get("next_frontier")
    summary["next_frontier_present"] = next_frontier is not None
    if isinstance(next_frontier, Mapping):
        summary["next_frontier"] = _retained_frontier_row_summary(next_frontier)
    elif next_frontier is not None:
        summary["next_frontier"] = next_frontier

    closed: set[str] = set()
    terminal_rows: list[dict[str, Any]] = []
    residual_rows: list[dict[str, Any]] = []
    for key in ("terminal_frontiers", "frontiers"):
        rows = entry.get(key)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            normalized = _retained_frontier_row_summary(row)
            family = normalized.get("family_id")
            terminal = key == "terminal_frontiers" or _retained_frontier_terminal(row)
            if terminal:
                terminal_rows.append(normalized)
                if isinstance(family, str) and family:
                    closed.add(family)
            else:
                residual_rows.append(normalized)

    summary["closed_families"] = sorted(closed)
    summary["terminal_frontiers"] = terminal_rows
    summary["residual_frontiers"] = residual_rows
    return summary


def _retained_function_entry(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    function: str,
) -> Mapping[str, Any] | None:
    if not isinstance(retained_frontiers, Mapping):
        return None
    functions = retained_frontiers.get("functions")
    if not isinstance(functions, Sequence) or isinstance(functions, (str, bytes)):
        return None
    for entry in functions:
        if isinstance(entry, Mapping) and entry.get("function") == function:
            return entry
    return None


def _retained_frontier_terminal(row: Mapping[str, Any]) -> bool:
    if row.get("terminal") is True:
        return True
    if row.get("terminal_reason"):
        return True
    status = str(row.get("status") or "").lower()
    return status in {"terminal", "blocked", "terminal-blocker", "copy-found"}


def _retained_frontier_row_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "kind",
        "family_id",
        "status",
        "actionable",
        "terminal_reason",
        "terminal_blocker",
        "candidate_id",
        "route_id",
        "source_file",
        "source_path",
        "source_retained",
        "path",
        "post_ceiling_route_signatures",
        "post_ceiling_route_signature_details",
        "route_terminal_blockers",
        "closed_by",
    ):
        value = row.get(key)
        if value is not None:
            out[key] = value
    return out


def _retained_closed_baseline_escape_families(
    retained_source_model_proof: Mapping[str, Any],
) -> set[str]:
    closed: set[str] = set()
    for key in ("closed_families", "suppressed_families"):
        closed.update(_string_items(retained_source_model_proof.get(key)))
    synthesis = retained_source_model_proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        for key in ("closed_families", "suppressed_families"):
            closed.update(_string_items(synthesis.get(key)))
    exhausted = retained_source_model_proof.get("exhausted_dimensions")
    if isinstance(exhausted, Sequence) and not isinstance(exhausted, (str, bytes)):
        for row in exhausted:
            if not isinstance(row, Mapping):
                continue
            dimension_id = _string_or_none(row.get("dimension_id"))
            if dimension_id is None:
                continue
            closed.update(_baseline_escape_families_for_dimension(dimension_id))
    return closed


def _baseline_escape_families_for_dimension(dimension_id: str) -> set[str]:
    if dimension_id == "sort-init-indexed-write":
        return {"post_ceiling_sort_loop_shape"}
    if dimension_id in {
        "sort-indexed-byte-cache",
        "sort-call-return-copy-local",
    }:
        return {"post_ceiling_sort_address_value_pair"}
    if dimension_id == "sort-swap-slot-lvalue":
        return {"post_ceiling_sort_swap_materialization"}
    return set()


def _retained_all_supported_baseline_escape_closed(
    *,
    function: str,
    evidence: Mapping[str, Any],
) -> bool:
    if not _is_sort_profile(function):
        return False
    retained = evidence.get("retained_frontiers")
    if not isinstance(retained, Mapping):
        return False
    if retained.get("status") != _RETAINED_EXHAUSTED_STATUS:
        return False
    if retained.get("next_frontier_present") is True:
        return False
    proof = evidence.get("retained_source_model_proof")
    if not isinstance(proof, Mapping) or not proof:
        return False
    closed = set(evidence.get("suppressed_families") or [])
    required = set(_transform_family_hints(function=function))
    return bool(required) and required <= closed


def _retained_all_known_terminal_summary(
    *,
    function: str,
    source_function: str | None,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    final_force = _normalized_int_mapping(evidence.get("final_force_phys"))
    proof = evidence.get("retained_source_model_proof")
    proof_summary = proof if isinstance(proof, Mapping) else {}
    summary: dict[str, Any] = {
        "status": "terminal",
        "kind": FINAL_TERMINAL_KIND,
        "terminal_blocker": TERMINAL_BLOCKER,
        "terminal_reason": FINAL_TERMINAL_REASON,
        "family_id": FINAL_SYNTHESIS_FAMILY,
        "suppression_family": FINAL_SYNTHESIS_FAMILY,
        "function": function,
        "source_function": source_function,
        "final_force_phys": final_force,
        "attempted_targets": final_force,
        "target_anchors": evidence.get("target_anchors", []),
        "retained_frontiers": evidence.get("retained_frontiers", {}),
        "source_model_proof": proof_summary,
        "next_unsupported_source_model": proof_summary.get(
            "next_unsupported_source_model"
        ),
        "next_unsupported_source_family": proof_summary.get(
            "next_unsupported_source_family"
        ),
        "source_spans": proof_summary.get("source_spans", []),
        "source_hunks_by_candidate": proof_summary.get(
            "source_hunks_by_candidate",
            [],
        ),
    }
    exhausted = proof_summary.get("exhausted_dimensions")
    if isinstance(exhausted, list):
        summary["exhausted_dimensions"] = exhausted
    return summary


def _retained_current_ceiling(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    entry: Mapping[str, Any],
    meta: Mapping[str, Any],
    function: str,
) -> Mapping[str, Any] | None:
    for source in (meta, entry, retained_frontiers):
        if not isinstance(source, Mapping):
            continue
        current = source.get("current_ceiling")
        if isinstance(current, Mapping) and current.get("function") in (None, function):
            return current
    return None


def _first_present_mapping_value(
    key: str,
    *sources: Mapping[str, Any] | None,
) -> Any:
    for source in sources:
        if isinstance(source, Mapping) and source.get(key) is not None:
            return source[key]
    return None


def _retained_continuation_family_closed(evidence: Mapping[str, Any]) -> bool:
    retained = evidence.get("retained_frontiers")
    if not isinstance(retained, Mapping):
        return False
    if retained.get("status") != _RETAINED_EXHAUSTED_STATUS:
        return False
    if retained.get("next_frontier_present") is True:
        return False
    closed = retained.get("closed_families")
    return (
        isinstance(closed, Sequence)
        and not isinstance(closed, (str, bytes))
        and CONTINUATION_FAMILY in set(str(item) for item in closed)
    )


def _retained_continuation_terminal_without_routes(
    evidence: Mapping[str, Any],
) -> bool:
    if not _retained_continuation_family_closed(evidence):
        return False
    for row in _retained_continuation_frontiers(evidence):
        signatures = row.get("post_ceiling_route_signatures")
        if (
            isinstance(signatures, Sequence)
            and not isinstance(signatures, (str, bytes))
            and any(isinstance(signature, str) and signature for signature in signatures)
        ):
            continue
        if row.get("kind") == CONTINUATION_TERMINAL_KIND:
            return True
        if row.get("terminal_reason") == CONTINUATION_TERMINAL_REASON:
            return True
    return False


def _continuation_routes_closed_by_retained(
    evidence: Mapping[str, Any],
    continuation_summary: Mapping[str, Any] | None,
) -> bool:
    if not _retained_continuation_family_closed(evidence):
        return False
    if not isinstance(continuation_summary, Mapping):
        return False
    if continuation_summary.get("status") != "source-actionable":
        return False
    coverage = _continuation_route_signature_coverage(continuation_summary)
    current_signatures = coverage["signatures"]
    if not current_signatures:
        return False
    if coverage["route_count"] != len(current_signatures):
        return False
    closed_signatures = _retained_closed_route_signatures(evidence)
    return bool(closed_signatures) and set(current_signatures) <= closed_signatures


def _retained_continuation_frontiers(
    evidence: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    retained = evidence.get("retained_frontiers")
    if not isinstance(retained, Mapping):
        return []
    rows: list[Mapping[str, Any]] = []
    for row in retained.get("terminal_frontiers") or []:
        if (
            isinstance(row, Mapping)
            and row.get("family_id") == CONTINUATION_FAMILY
        ):
            rows.append(row)
    return rows


def _retained_closed_route_signatures(evidence: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in _retained_continuation_frontiers(evidence):
        signatures = row.get("post_ceiling_route_signatures")
        if isinstance(signatures, Sequence) and not isinstance(signatures, (str, bytes)):
            out.update(str(signature) for signature in signatures if signature)
        blockers = row.get("route_terminal_blockers")
        if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
            continue
        for blocker in blockers:
            if not isinstance(blocker, Mapping):
                continue
            signature = blocker.get("post_ceiling_route_signature")
            if isinstance(signature, str) and signature:
                out.add(signature)
    return out


def _continuation_route_signatures(
    continuation_summary: Mapping[str, Any],
) -> list[str]:
    return _continuation_route_signature_coverage(continuation_summary)["signatures"]


def _continuation_route_signature_coverage(
    continuation_summary: Mapping[str, Any],
) -> dict[str, Any]:
    ranked = continuation_summary.get("ranked_candidates")
    if not isinstance(ranked, Sequence) or isinstance(ranked, (str, bytes)):
        return {
            "route_count": 0,
            "signatures": [],
            "unsigned_routes": [],
        }
    out: list[str] = []
    unsigned: list[dict[str, Any]] = []
    route_count = 0
    for row in ranked:
        if not isinstance(row, Mapping):
            continue
        continuation = row.get("continuation")
        if not isinstance(continuation, Mapping):
            continue
        route_count += 1
        signature = _post_ceiling_route_signature(
            route=str(continuation.get("route") or ""),
            function=str(continuation_summary.get("function") or ""),
            class_id=_int_or_none(continuation_summary.get("class_id")),
            target_orders=_normalized_target_orders(
                continuation.get("target_orders")
            ),
            final_force=(
                _normalized_int_mapping(row.get("candidate_force_phys"))
                or _normalized_int_mapping(
                    continuation_summary.get("final_force_phys")
                )
            ),
            source_file=_non_empty_str(continuation.get("source_retained")),
            pcdump=_non_empty_str(continuation.get("pcdump_path")),
        )
        if signature is not None:
            out.append(signature)
        else:
            unsigned.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "route": continuation.get("route"),
                }
            )
    return {
        "route_count": route_count,
        "signatures": out,
        "unsigned_routes": unsigned,
    }


def _post_ceiling_route_signature(
    *,
    route: str,
    function: str,
    class_id: int | None,
    target_orders: Sequence[Sequence[int]],
    final_force: Mapping[str, int],
    source_file: str | None,
    pcdump: str | None,
) -> str | None:
    if not route or not target_orders or not final_force:
        return None
    return _json_key(
        {
            "route": route,
            "function": function,
            "class_id": class_id,
            "target_orders": [list(order) for order in target_orders],
            "force": dict(final_force),
            "source": _path_signature(source_file),
            "pcdump": _path_signature(pcdump),
        }
    )


def _normalized_target_orders(raw: Any) -> list[list[int]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    out: list[list[int]] = []
    for row in raw:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            continue
        if len(row) != 2:
            continue
        before = _int_or_none(row[0])
        after = _int_or_none(row[1])
        if before is not None and after is not None:
            out.append([before, after])
    return out


def _path_signature(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path)


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _non_empty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _best_expression_score(payload: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    best = payload.get("best_candidate")
    if isinstance(best, Mapping) and isinstance(best.get("expression_score"), Mapping):
        return best["expression_score"]
    ranked = payload.get("ranked_candidates")
    if isinstance(ranked, Sequence) and not isinstance(ranked, (str, bytes)):
        for row in ranked:
            if isinstance(row, Mapping) and isinstance(row.get("expression_score"), Mapping):
                return row["expression_score"]
    return _first_mapping_by_key(payload, "expression_score")


def _expression_targets(expression_score: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(expression_score, Mapping):
        return []
    virtuals = expression_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return []
    anchors: list[dict[str, Any]] = []
    for virtual, raw in virtuals.items():
        if not isinstance(raw, Mapping):
            continue
        source = raw.get("baseline_source")
        signature = raw.get("signature")
        anchors.append({
            "virtual": _int_or_str(virtual),
            "baseline_virtual": _int_or_none(virtual),
            "name": (
                source.get("name") if isinstance(source, Mapping) else raw.get("name")
            ),
            "expression": (
                source.get("expression")
                if isinstance(source, Mapping)
                else (
                    signature.get("expression")
                    if isinstance(signature, Mapping)
                    else None
                )
            ),
            "expected": _int_or_none(raw.get("expected")),
            "actual": _int_or_none(raw.get("actual")),
            "matched": raw.get("matched"),
        })
    return anchors


def _target_score_force_phys(payload: Mapping[str, Any] | None) -> dict[str, int]:
    target_score = _first_mapping_by_key(payload, "target_score")
    if not isinstance(target_score, Mapping):
        return {}
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}
    out: dict[str, int] = {}
    for virtual, raw in virtuals.items():
        if not isinstance(raw, Mapping):
            continue
        expected = _int_or_none(raw.get("expected"))
        if expected is not None:
            out[str(virtual)] = expected
    return out


def _force_phys_from_payload(payload: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    out: dict[str, int] = {}
    for source in (
        payload.get("force_phys"),
        _nested_get(payload, ("target_spec", "virtuals")),
        payload.get("virtuals"),
    ):
        if isinstance(source, Mapping):
            for virtual, reg in source.items():
                parsed = _int_or_none(reg)
                if parsed is not None:
                    out[str(virtual)] = parsed
    targets = payload.get("targets")
    if isinstance(targets, Sequence) and not isinstance(targets, (str, bytes)):
        for target in targets:
            if not isinstance(target, Mapping):
                continue
            virtual = target.get("ig_idx") or target.get("virtual")
            reg = target.get("target_reg") or target.get("expected")
            parsed_virtual = _int_or_none(virtual)
            parsed_reg = _int_or_none(reg)
            if parsed_virtual is not None and parsed_reg is not None:
                out[str(parsed_virtual)] = parsed_reg
    return out


def _score_force_phys_summary(
    score_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    out: dict[str, int] = {}
    sources: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for index, score_row in enumerate(score_rows):
        if not isinstance(score_row, Mapping):
            continue
        candidate_id = score_row.get("candidate_id")
        for score_source in ("target_score", "expression_score"):
            score = _nested_mapping(score_row, (score_source,))
            if not isinstance(score, Mapping):
                continue
            virtuals = score.get("virtuals")
            if not isinstance(virtuals, Mapping):
                continue
            for virtual, raw in virtuals.items():
                if not isinstance(raw, Mapping):
                    continue
                parsed_virtual = _int_or_none(virtual)
                expected = _int_or_none(raw.get("expected"))
                if parsed_virtual is None or expected is None:
                    continue
                key = str(parsed_virtual)
                current = out.get(key)
                source = {
                    "candidate_id": candidate_id,
                    "row_index": index,
                    "score_source": score_source,
                    "virtual": parsed_virtual,
                    "expected": expected,
                }
                if current is None:
                    out[key] = expected
                    sources[key] = source
                elif current != expected:
                    conflicts.append(
                        {
                            "virtual": parsed_virtual,
                            "previous_expected": current,
                            "current_expected": expected,
                            "previous_source": sources.get(key),
                            "current_source": source,
                        }
                    )
    return {
        "force_phys": out,
        "conflicts": conflicts,
        "sources": sources,
    }


def _force_phys_from_score_rows(
    score_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return _score_force_phys_summary(score_rows)["force_phys"]


def _merged_force_phys(*sources: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for source in sources:
        for key, value in _normalized_int_mapping(source).items():
            out.setdefault(key, value)
    return out


def _evidence_with_final_force(
    evidence: Mapping[str, Any],
    final_force_phys: Mapping[str, int],
) -> dict[str, Any]:
    updated = dict(evidence)
    final_force = _normalized_int_mapping(final_force_phys)
    updated["final_force_phys"] = final_force
    updated["attempted_targets"] = final_force
    if not updated.get("target_anchors"):
        updated["target_anchors"] = _target_anchors_from_force_phys(final_force)
    return updated


def _post_ceiling_final_synthesis_summary(
    *,
    function: str,
    source_function: str | None,
    terminal_summary: Mapping[str, Any],
    score_rows: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    force_conflicts: Sequence[Mapping[str, Any]] = (),
    continuation_summary: Mapping[str, Any] | None = None,
    source_text: str | None = None,
    generated_candidates: Sequence[Mapping[str, Any]] = (),
    validation_options: Mapping[str, Any] | None = None,
    include_source: bool = False,
) -> dict[str, Any]:
    retained = evidence.get("retained_frontiers")
    retained_summary = retained if isinstance(retained, Mapping) else {}
    final_force = _merged_force_phys(
        terminal_summary.get("final_force_phys"),
        evidence.get("final_force_phys"),
        _force_phys_from_score_rows(score_rows),
    )
    summary: dict[str, Any] = {
        "status": "terminal",
        "kind": FINAL_TERMINAL_KIND,
        "terminal_blocker": TERMINAL_BLOCKER,
        "terminal_reason": FINAL_TERMINAL_REASON,
        "family_id": FINAL_SYNTHESIS_FAMILY,
        "suppression_family": FINAL_SYNTHESIS_FAMILY,
        "function": function,
        "source_function": source_function,
        "final_force_phys": final_force,
        "attempted_targets": final_force,
        "target_anchors": evidence.get("target_anchors", []),
        "residual_blocker_targets": _residual_blocker_targets(
            score_rows,
            final_force,
        ),
        "closed_families": list(retained_summary.get("closed_families") or []),
        "retained_frontiers": retained_summary,
        "terminal_summary_kind": terminal_summary.get("kind"),
        "terminal_summary_reason": terminal_summary.get("terminal_reason"),
    }
    retained_proof = evidence.get("retained_source_model_proof")
    if isinstance(retained_proof, Mapping):
        for key in (
            "next_unsupported_source_model",
            "next_unsupported_source_family",
        ):
            value = retained_proof.get(key)
            if value is not None:
                summary[key] = value
        if retained_proof:
            summary["source_model_proof"] = dict(retained_proof)
    if force_conflicts:
        summary["force_map_conflicts"] = [dict(row) for row in force_conflicts]
    if isinstance(continuation_summary, Mapping):
        route_coverage = _continuation_route_signature_coverage(continuation_summary)
        summary["current_route_signatures"] = route_coverage["signatures"]
        summary["current_route_signature_coverage"] = route_coverage
        summary["closed_route_signatures"] = sorted(
            _retained_closed_route_signatures(evidence)
        )
    if source_text is not None and not force_conflicts:
        summary["post_ceiling_source_family_discovery"] = (
            _post_ceiling_source_family_discovery_summary(
                source_text=source_text,
                function=function,
                source_function=source_function,
                final_summary=summary,
                score_rows=score_rows,
                generated_candidates=generated_candidates,
                evidence=evidence,
                validation_options=validation_options or {},
                include_source=include_source,
            )
        )
    return summary


def _post_ceiling_source_family_discovery_summary(
    *,
    source_text: str,
    function: str,
    source_function: str | None,
    final_summary: Mapping[str, Any],
    score_rows: Sequence[Mapping[str, Any]],
    generated_candidates: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    validation_options: Mapping[str, Any],
    include_source: bool,
) -> dict[str, Any]:
    function_name = source_function or _SOURCE_FUNCTION_ALIASES.get(function) or function
    span = find_function(source_text, function_name)
    if span is None and function_name != function:
        span = find_function(source_text, function)
        if span is not None:
            function_name = function
    final_force = _merged_force_phys(
        final_summary.get("final_force_phys"),
        evidence.get("final_force_phys"),
        _force_phys_from_score_rows(score_rows),
    )
    target_anchors = _list_of_mappings(
        final_summary.get("target_anchors") or evidence.get("target_anchors")
    )
    residual_targets = _list_of_mappings(final_summary.get("residual_blocker_targets"))
    metadata_options = dict(validation_options)
    metadata_options.setdefault("function", function)
    metadata_options.setdefault("source_function", function_name)
    metadata = _validation_metadata(evidence, metadata_options)
    candidate_map = {
        str(candidate.get("candidate_id")): candidate
        for candidate in generated_candidates
        if isinstance(candidate, Mapping) and candidate.get("candidate_id") is not None
    }
    retained_inputs = _retained_scored_probe_inputs(
        score_rows,
        candidate_map=candidate_map,
    )
    missing_inputs = _discovery_missing_inputs(score_rows, retained_inputs)

    if span is None:
        dimensions = _source_family_dimension_specs(function)
        return {
            "status": "terminal",
            "kind": SOURCE_FAMILY_DISCOVERY_KIND,
            "family_id": SOURCE_FAMILY_DISCOVERY_FAMILY,
            "terminal_reason": SOURCE_FAMILY_DISCOVERY_TERMINAL_REASON,
            "trigger_terminal_reason": FINAL_TERMINAL_REASON,
            "bounded": True,
            "max_candidates": len(dimensions),
            "function": function,
            "source_function": function_name,
            "final_force_phys": final_force,
            "target_anchors": target_anchors,
            "residual_blocker_targets": residual_targets,
            "source_neighborhoods": [],
            "terminal_target_spans": [],
            "generated_family_dimensions": dimensions,
            "source_family_dimensions": dimensions,
            "probes": [],
            "candidates": [],
            "candidate_count": 0,
            "retained_scored_probes": retained_inputs,
            "retained_candidate_inputs": retained_inputs,
            "scored_count": len(retained_inputs),
            "exhausted_dimensions": [
                {
                    **dimension,
                    "status": "source-span-missing",
                    "exhaustion_reason": "source-function-not-found",
                }
                for dimension in dimensions
            ],
            "missing_inputs": [
                *missing_inputs,
                {
                    "input": "source_function",
                    "reason": "function-not-found",
                    "value": function_name,
                },
            ],
        }

    neighborhoods = _source_family_neighborhoods(
        source_text,
        function_span=span,
        function=function,
        source_function=function_name,
        target_anchors=target_anchors,
        final_force_phys=final_force,
        validation_options=metadata_options,
    )
    probes = _source_family_discovery_probes(
        source_text,
        function_span=span,
        function=function,
        source_function=function_name,
        neighborhoods=neighborhoods,
        validation_metadata=metadata,
        retained_inputs=retained_inputs,
        include_source=include_source,
    )
    dimensions = _source_family_dimensions(
        function=function,
        neighborhoods=neighborhoods,
        probes=probes,
        retained_inputs=retained_inputs,
    )
    exhausted_dimensions = [
        dict(dimension)
        for dimension in dimensions
        if (
            not dimension.get("span_ids")
            or dimension.get("status") == "scored-terminal"
        )
    ]
    status = "source-actionable" if probes else "terminal"
    summary: dict[str, Any] = {
        "status": status,
        "kind": SOURCE_FAMILY_DISCOVERY_KIND,
        "family_id": SOURCE_FAMILY_DISCOVERY_FAMILY,
        "trigger_terminal_reason": FINAL_TERMINAL_REASON,
        "bounded": True,
        "max_candidates": len(_source_family_dimension_specs(function)),
        "function": function,
        "source_function": function_name,
        "final_force_phys": final_force,
        "target_anchors": target_anchors,
        "residual_blocker_targets": residual_targets,
        "source_neighborhoods": neighborhoods,
        "terminal_target_spans": neighborhoods,
        "generated_family_dimensions": dimensions,
        "source_family_dimensions": dimensions,
        "probes": probes,
        "candidates": probes,
        "candidate_count": len(probes),
        "retained_scored_probes": retained_inputs,
        "retained_candidate_inputs": retained_inputs,
        "scored_count": len(retained_inputs),
        "missing_inputs": missing_inputs,
    }
    if not probes:
        summary["terminal_reason"] = SOURCE_FAMILY_DISCOVERY_TERMINAL_REASON
        summary["exhausted_dimensions"] = exhausted_dimensions or [
            {
                **dimension,
                "status": "probe-not-generated",
                "exhaustion_reason": "no-source-changing-probe",
            }
            for dimension in dimensions
        ]
    return summary


def _source_family_dimension_specs(function: str) -> list[dict[str, Any]]:
    if _is_sort_profile(function):
        return [
            {
                "dimension_id": "sort-init-indexed-write",
                "neighborhood_id": "sort-init-pointer-walk",
                "description": "alternate sorted_names/totals initialization write form",
                "operations": ["indexed-write", "pointer-lifetime-split"],
            },
            {
                "dimension_id": "sort-indexed-byte-cache",
                "neighborhood_id": "sort-max-idx-indexed-byte",
                "description": "cache max_idx and j sorted_names byte values",
                "operations": ["indexed-byte-cache", "callarg-reuse"],
            },
            {
                "dimension_id": "sort-call-return-copy-local",
                "neighborhood_id": "sort-call-return-copy",
                "description": "materialize GetNameText(j) call return as a copy local",
                "operations": ["call-return-copy", "degree-zero-residual-steering"],
            },
            {
                "dimension_id": "sort-swap-slot-lvalue",
                "neighborhood_id": "sort-swap-materialization",
                "description": "materialize selected sorted_names slot as an lvalue",
                "operations": ["slot-lvalue", "copy-materialization"],
            },
        ]
    return [
        {
            "dimension_id": "draw-col-cast-product-local",
            "neighborhood_id": "draw-col-offset-product",
            "description": "materialize the col cast and product as source locals",
            "operations": ["cast-local", "product-local"],
        },
        {
            "dimension_id": "draw-row-translation-scale-split",
            "neighborhood_id": "draw-row-offset-scale",
            "description": "split row translation delta from the row scale product",
            "operations": ["translation-delta-local", "scale-product-local"],
        },
        {
            "dimension_id": "draw-digit-callarg-fsubs-temp",
            "neighborhood_id": "draw-digit-callarg",
            "description": "materialize a digit animation fsubs-style call argument",
            "operations": ["callarg-temp", "fsubs-temp"],
        },
    ]


def _source_family_neighborhoods(
    source_text: str,
    *,
    function_span: Any,
    function: str,
    source_function: str,
    target_anchors: Sequence[Mapping[str, Any]],
    final_force_phys: Mapping[str, int],
    validation_options: Mapping[str, Any],
) -> list[dict[str, Any]]:
    function_text = source_text[function_span.sig_start:function_span.full_end]
    specs = _source_family_dimension_specs(function)
    neighborhoods: list[dict[str, Any]] = []
    for spec in specs:
        match = _source_family_neighborhood_match(
            function_text,
            neighborhood_id=str(spec["neighborhood_id"]),
        )
        if match is None:
            continue
        abs_start = function_span.sig_start + match.start()
        abs_end = function_span.sig_start + match.end()
        line_start, line_end, snippet = _line_range_snippet(
            source_text,
            abs_start,
            abs_end,
        )
        anchor_virtuals = _neighborhood_anchor_virtuals(
            str(spec["neighborhood_id"])
        )
        anchor_rows = _anchors_for_virtuals(target_anchors, anchor_virtuals)
        neighborhoods.append(
            {
                "span_id": spec["neighborhood_id"],
                "neighborhood_id": spec["neighborhood_id"],
                "dimension_id": spec["dimension_id"],
                "source_file": validation_options.get("expression_source"),
                "source_function": source_function,
                "line_start": line_start,
                "line_end": line_end,
                "anchor_virtuals": anchor_virtuals,
                "anchor_names": [
                    anchor.get("name")
                    for anchor in anchor_rows
                    if anchor.get("name") is not None
                ],
                "expressions": [
                    anchor.get("expression")
                    for anchor in anchor_rows
                    if anchor.get("expression") is not None
                ],
                "force_targets": {
                    str(virtual): final_force_phys[str(virtual)]
                    for virtual in anchor_virtuals
                    if str(virtual) in final_force_phys
                },
                "source_excerpt": snippet,
            }
        )
    return neighborhoods


def _source_family_neighborhood_match(
    function_text: str,
    *,
    neighborhood_id: str,
) -> re.Match[str] | None:
    patterns = {
        "draw-col-offset-product": [
            r"(?P<indent>[ \t]*)col_offset\s*=\s*y_spacing\s*\*\s*\(f32\)\s*col\s*;",
        ],
        "draw-row-offset-scale": [
            r"(?P<indent>[ \t]*)row_offset\s*=\s*y_offset\s*\*\s*\(f32\)\s*row\s*;",
            (
                r"(?P<indent>[ \t]*)rowf\s*=\s*\(f32\)\s*row\s*;\s*\n"
                r"(?P=indent)[ \t]*row_offset\s*\*=\s*rowf\s*;"
            ),
        ],
        "draw-digit-callarg": [
            (
                r"(?P<indent>[ \t]*)base\s*=\s*\(f32\)\s*digit\s*;\s*\n"
                r"(?P=indent)[ \t]*HSD_JObjReqAnimAll\(\s*jobj\s*,\s*base\s*\)\s*;"
            ),
        ],
        "sort-init-pointer-walk": [
            (
                r"(?P<indent>[ \t]*)for \(n = 0; n < 0x78; n\+\+, dst_iter\+\+, tp\+\+\) \{\n"
                r"(?P=indent)[ \t]*\*dst_iter = \(u8\) n;\n"
                r"(?P=indent)[ \t]*\*tp = mnDiagram_SumNameKOs\(n & 0xFF\);\n"
                r"(?P=indent)\}"
            ),
        ],
        "sort-max-idx-indexed-byte": [_SORT_INDEXED_BYTE_IF_PATTERN],
        "sort-call-return-copy": [_SORT_INDEXED_BYTE_IF_PATTERN],
        "sort-swap-materialization": [
            (
                r"(?P<indent>[ \t]*)u8\* p = &assets->sorted_fighters\[max_idx\];\n"
                r"(?P=indent)[ \t]*u8 temp = \*\(p \+= sizeof\(mnDiagram_804A0750_t\)\);"
            ),
        ],
    }
    for pattern in patterns.get(neighborhood_id, []):
        match = re.search(pattern, function_text, re.MULTILINE)
        if match is not None:
            return match
    return None


def _source_family_discovery_probes(
    source_text: str,
    *,
    function_span: Any,
    function: str,
    source_function: str,
    neighborhoods: Sequence[Mapping[str, Any]],
    validation_metadata: Mapping[str, Any],
    retained_inputs: Sequence[Mapping[str, Any]],
    include_source: bool,
) -> list[dict[str, Any]]:
    function_text = source_text[function_span.sig_start:function_span.full_end]
    neighborhood_ids = {
        str(neighborhood.get("neighborhood_id")) for neighborhood in neighborhoods
    }
    pcdump_from = _first_retained_value(retained_inputs, "pcdump_path")
    if _is_sort_profile(function):
        specs = [
            (
                "post-ceiling-source-family-sort-init-indexed-write",
                "post_ceiling_source_family_sort_init_indexed_write",
                "sort-init-indexed-write",
                "sort-init-pointer-walk",
                "init-indexed-write",
                "Rewrite init pointer progression as indexed writes.",
                "tests whether indexed writes alter IG34/IG44 ownership",
                _patch_discovery_sort_init_indexed_write,
            ),
            (
                "post-ceiling-source-family-sort-indexed-byte-cache",
                "post_ceiling_source_family_sort_indexed_byte_cache",
                "sort-indexed-byte-cache",
                "sort-max-idx-indexed-byte",
                "indexed-byte-cache",
                "Cache max_idx and j sorted name bytes before comparisons.",
                "tests indexed byte access lifetimes without retrying old families",
                _patch_discovery_sort_indexed_byte_cache,
            ),
            (
                "post-ceiling-source-family-sort-call-return-copy-local",
                "post_ceiling_source_family_sort_call_return_copy_local",
                "sort-call-return-copy-local",
                "sort-call-return-copy",
                "call-return-copy-local",
                "Materialize the GetNameText(j) call return through a copy local.",
                "targets IG34->r27 while preserving the existing IG44->r25 byte-cache hit",
                _patch_discovery_sort_call_return_copy_local,
            ),
            (
                "post-ceiling-source-family-sort-swap-slot-lvalue",
                "post_ceiling_source_family_sort_swap_slot_lvalue",
                "sort-swap-slot-lvalue",
                "sort-swap-materialization",
                "swap-slot-lvalue",
                "Materialize the selected sorted_names slot as an lvalue.",
                "tests swap/materialization lifetime while preserving IG34/IG44 targets",
                _patch_discovery_sort_swap_slot_lvalue,
            ),
        ]
    else:
        specs = [
            (
                "post-ceiling-source-family-draw-col-cast-product-local",
                "post_ceiling_source_family_draw_col_cast_product_local",
                "draw-col-cast-product-local",
                "draw-col-offset-product",
                "col-cast-product-local",
                "Materialize the column cast and product as source locals.",
                "tests the col_offset IG32 lifetime outside exhausted product owners",
                _patch_discovery_draw_col_product_local,
            ),
            (
                "post-ceiling-source-family-draw-row-translation-scale-split",
                "post_ceiling_source_family_draw_row_translation_scale_split",
                "draw-row-translation-scale-split",
                "draw-row-offset-scale",
                "row-translation-scale-split",
                "Split the row translation delta and row-scale product.",
                "tests row_offset IG37 ownership beyond predefined row families",
                _patch_discovery_draw_row_scale_split,
            ),
            (
                "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
                "post_ceiling_source_family_draw_digit_callarg_fsubs_temp",
                "draw-digit-callarg-fsubs-temp",
                "draw-digit-callarg",
                "digit-callarg-fsubs-temp",
                "Materialize a digit animation fsubs-style call argument.",
                "tests the IG46 call-argument temp as a new source family",
                _patch_discovery_draw_digit_callarg_fsubs_temp,
            ),
        ]
    probes: list[dict[str, Any]] = []
    seen: set[str] = set()
    retained_probe_ids = {
        str(row.get("candidate_id"))
        for row in retained_inputs
        if isinstance(row, Mapping) and row.get("candidate_id") is not None
    }
    for (
        probe_id,
        family,
        dimension_id,
        neighborhood_id,
        strategy,
        rationale,
        expected_effect,
        patcher,
    ) in specs:
        if neighborhood_id not in neighborhood_ids:
            continue
        if probe_id in retained_probe_ids:
            continue
        patched_function = patcher(function_text)
        if patched_function is None or patched_function == function_text:
            continue
        patched_source = (
            source_text[:function_span.sig_start]
            + patched_function
            + source_text[function_span.full_end:]
        )
        if patched_source in seen:
            continue
        seen.add(patched_source)
        source_hunks = [
            hunk.to_dict() for hunk in diff_line_hunks(
                source_text,
                patched_source,
                hunk_prefix=f"{probe_id}-h",
            )
        ]
        probe = {
                "probe_id": probe_id,
                "candidate_id": probe_id,
                "family": family,
                "dimension_id": dimension_id,
                "span_ids": [neighborhood_id],
                "strategy": strategy,
                "rationale": rationale,
                "expected_effect": expected_effect,
                "source_hunks": source_hunks,
                "validation_metadata": dict(validation_metadata),
                "source_function": source_function,
                "pcdump_from": pcdump_from,
            }
        if include_source:
            probe["source_text"] = patched_source
        probes.append(probe)
    return probes


def sort_source_family_patcher_specs() -> list[dict[str, Any]]:
    """Return the existing bounded Sort source-family patchers.

    The post-meta synthesis command builds a broader candidate set, but its
    seed probes should stay tied to the baseline-escape regexes that already
    encode the retained Sort source neighborhoods.
    """

    return [
        {
            "variant_id": "indexed-write",
            "dimension_id": "sort-init-indexed-write",
            "neighborhood_id": "sort-init-pointer-walk",
            "equivalence_class": "init-indexed-write",
            "strategy": "init-indexed-write",
            "rationale": "Rewrite init pointer progression as indexed writes.",
            "expected_effect": "tests whether indexed writes alter IG34/IG44 ownership",
            "patcher": _patch_discovery_sort_init_indexed_write,
        },
        {
            "variant_id": "byte-cache",
            "dimension_id": "sort-indexed-byte-cache",
            "neighborhood_id": "sort-max-idx-indexed-byte",
            "equivalence_class": "indexed-byte-cache",
            "strategy": "indexed-byte-cache",
            "rationale": "Cache max_idx and j sorted name bytes before comparisons.",
            "expected_effect": "tests indexed byte access lifetimes",
            "patcher": _patch_discovery_sort_indexed_byte_cache,
        },
        {
            "variant_id": "j-text-copy",
            "dimension_id": "sort-call-return-copy-local",
            "neighborhood_id": "sort-call-return-copy",
            "equivalence_class": "call-return-copy-local",
            "strategy": "call-return-copy-local",
            "rationale": "Materialize the GetNameText(j) return through a copy local.",
            "expected_effect": "targets the IG34 call-return copy boundary",
            "patcher": _patch_discovery_sort_call_return_copy_local,
        },
        {
            "variant_id": "selected-slot-lvalue",
            "dimension_id": "sort-swap-slot-lvalue",
            "neighborhood_id": "sort-swap-materialization",
            "equivalence_class": "swap-slot-lvalue",
            "strategy": "swap-slot-lvalue",
            "rationale": "Materialize the selected sorted_names slot as an lvalue.",
            "expected_effect": "tests selected-slot materialization lifetime",
            "patcher": _patch_discovery_sort_swap_slot_lvalue,
        },
    ]


def draw_source_family_patcher_specs() -> list[dict[str, Any]]:
    """Return the existing bounded Draw FPR source-family patchers."""

    return [
        {
            "variant_id": "col-product-local",
            "dimension_id": "draw-col-cast-product-local",
            "neighborhood_id": "draw-col-offset-product",
            "equivalence_class": "col-cast-product-local",
            "strategy": "col-cast-product-local",
            "rationale": "Materialize the column cast and product as source locals.",
            "expected_effect": "tests the col_offset IG32 FPR lifetime",
            "patcher": _patch_discovery_draw_col_product_local,
        },
        {
            "variant_id": "row-scale-split",
            "dimension_id": "draw-row-translation-scale-split",
            "neighborhood_id": "draw-row-offset-scale",
            "equivalence_class": "row-translation-scale-split",
            "strategy": "row-translation-scale-split",
            "rationale": "Split the row translation delta and row-scale product.",
            "expected_effect": "tests row_offset IG37 ownership beyond row families",
            "patcher": _patch_discovery_draw_row_scale_split,
        },
        {
            "variant_id": "digit-fsubs-temp",
            "dimension_id": "draw-digit-callarg-fsubs-temp",
            "neighborhood_id": "draw-digit-callarg",
            "equivalence_class": "digit-callarg-fsubs-temp",
            "strategy": "digit-callarg-fsubs-temp",
            "rationale": "Materialize a digit animation fsubs-style call argument.",
            "expected_effect": "tests the IG46 call-argument temp source boundary",
            "patcher": _patch_discovery_draw_digit_callarg_fsubs_temp,
        },
    ]


def patch_sort_init_pointer_walk(function_text: str, replacement_for_match: Any) -> str | None:
    """Patch the retained Sort initialization loop using the shared matcher."""

    return _replace_first(
        function_text,
        (
            r"(?P<indent>[ \t]*)for \(n = 0; n < 0x78; n\+\+, dst_iter\+\+, tp\+\+\) \{\n"
            r"(?P=indent)[ \t]*\*dst_iter = \(u8\) n;\n"
            r"(?P=indent)[ \t]*\*tp = mnDiagram_SumNameKOs\(n & 0xFF\);\n"
            r"(?P=indent)\}"
        ),
        replacement_for_match,
    )


def patch_sort_indexed_byte_comparison(
    function_text: str,
    replacement_for_match: Any,
) -> str | None:
    """Patch the retained Sort indexed-byte comparison using the shared matcher."""

    return _replace_first(
        function_text,
        _SORT_INDEXED_BYTE_IF_PATTERN,
        replacement_for_match,
    )


def patch_sort_swap_materialization(
    function_text: str,
    replacement_for_match: Any,
) -> str | None:
    """Patch the retained Sort selected-slot materialization using the shared matcher."""

    return _replace_first(
        function_text,
        (
            r"(?P<indent>[ \t]*)u8\* p = &assets->sorted_fighters\[max_idx\];\n"
            r"(?P=indent)[ \t]*u8 temp = \*\(p \+= sizeof\(mnDiagram_804A0750_t\)\);"
        ),
        replacement_for_match,
    )


def _source_family_dimensions(
    *,
    function: str,
    neighborhoods: Sequence[Mapping[str, Any]],
    probes: Sequence[Mapping[str, Any]],
    retained_inputs: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    neighborhoods_by_id = {
        str(neighborhood.get("neighborhood_id")): neighborhood
        for neighborhood in neighborhoods
    }
    probe_ids_by_dimension: dict[str, list[str]] = {}
    for probe in probes:
        dimension_id = str(probe.get("dimension_id"))
        probe_ids_by_dimension.setdefault(dimension_id, []).append(
            str(probe.get("probe_id"))
        )
    retained_probe_ids = {
        str(row.get("candidate_id"))
        for row in retained_inputs
        if isinstance(row, Mapping) and row.get("candidate_id") is not None
    }
    out: list[dict[str, Any]] = []
    for spec in _source_family_dimension_specs(function):
        neighborhood_id = str(spec["neighborhood_id"])
        dimension_id = str(spec["dimension_id"])
        span_ids = [neighborhood_id] if neighborhood_id in neighborhoods_by_id else []
        generated = sorted(probe_ids_by_dimension.get(dimension_id, []))
        expected_probe_id = f"post-ceiling-source-family-{dimension_id}"
        scored = (
            [expected_probe_id]
            if expected_probe_id in retained_probe_ids
            else []
        )
        if generated:
            status = "generated"
            exhaustion_reason = None
        elif scored and span_ids:
            status = "scored-terminal"
            exhaustion_reason = "retained-source-family-scored-no-progress"
        else:
            status = "source-span-missing"
            exhaustion_reason = "source-neighborhood-not-found"
        out.append(
            {
                **spec,
                "span_ids": span_ids,
                "generated_candidate_ids": generated,
                "scored_candidate_ids": scored,
                "status": status,
                "exhaustion_reason": exhaustion_reason,
            }
        )
    return out


def _retained_scored_probe_inputs(
    score_rows: Sequence[Mapping[str, Any]],
    *,
    candidate_map: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    for row in score_rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = row.get("candidate_id")
        candidate = candidate_map.get(str(candidate_id), {})
        pcdump_path = _string_or_none(row.get("pcdump_path"))
        source_retained = (
            _string_or_none(row.get("source_retained"))
            or _string_or_none(row.get("source_file"))
            or _string_or_none(row.get("path"))
            or _source_retained_from_pcdump(pcdump_path)
        )
        retained.append(
            {
                "candidate_id": candidate_id,
                "source_retained": source_retained,
                "pcdump_path": pcdump_path,
                "source_hunks": list(candidate.get("source_hunks") or []),
                "score_classification": row.get("classification"),
                "classification": row.get("classification"),
                "target_score": (
                    dict(row["target_score"])
                    if isinstance(row.get("target_score"), Mapping)
                    else None
                ),
                "expression_score": (
                    dict(row["expression_score"])
                    if isinstance(row.get("expression_score"), Mapping)
                    else None
                ),
                "candidate_force_phys": _force_phys_from_score_rows([row]),
                "route_signatures": list(
                    _string_items(row.get("post_ceiling_route_signatures"))
                ),
                "closed_by": row.get("closed_by"),
            }
        )
    return retained


def _discovery_missing_inputs(
    score_rows: Sequence[Mapping[str, Any]],
    retained_inputs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not score_rows:
        return [{"input": "score_rows", "reason": "no-retained-score-rows"}]
    missing: list[dict[str, Any]] = []
    for retained in retained_inputs:
        candidate_id = retained.get("candidate_id")
        if not retained.get("pcdump_path"):
            missing.append(
                {
                    "input": "pcdump_path",
                    "candidate_id": candidate_id,
                    "reason": "retained-pcdump-missing",
                }
            )
        if not retained.get("source_retained"):
            missing.append(
                {
                    "input": "source_retained",
                    "candidate_id": candidate_id,
                    "reason": "retained-source-missing",
                }
            )
    return missing


def _source_retained_from_pcdump(pcdump_path: str | None) -> str | None:
    if not pcdump_path:
        return None
    path = Path(pcdump_path)
    name = path.name
    if name.endswith(".pcdump.txt"):
        source = path.with_name(f"{name[:-len('.pcdump.txt')]}.c")
    elif name.endswith(".pcdump"):
        source = path.with_name(f"{name[:-len('.pcdump')]}.c")
    else:
        return None
    return str(source)


def _first_retained_value(
    retained_inputs: Sequence[Mapping[str, Any]],
    key: str,
) -> Any:
    for retained in retained_inputs:
        value = retained.get(key)
        if value:
            return value
    return None


def _neighborhood_anchor_virtuals(neighborhood_id: str) -> list[int]:
    return {
        "draw-col-offset-product": [32],
        "draw-row-offset-scale": [37],
        "draw-digit-callarg": [46],
        "sort-init-pointer-walk": [34, 44],
        "sort-max-idx-indexed-byte": [34],
        "sort-call-return-copy": [34, 44],
        "sort-swap-materialization": [44],
    }.get(neighborhood_id, [])


def _anchors_for_virtuals(
    target_anchors: Sequence[Mapping[str, Any]],
    virtuals: Sequence[int],
) -> list[Mapping[str, Any]]:
    wanted = {int(virtual) for virtual in virtuals}
    out: list[Mapping[str, Any]] = []
    for anchor in target_anchors:
        parsed = _int_or_none(
            anchor.get("baseline_virtual") or anchor.get("virtual")
        )
        if parsed in wanted:
            out.append(anchor)
    return out


def _line_range_snippet(
    source_text: str,
    start: int,
    end: int,
) -> tuple[int, int, str]:
    line_start_no = source_text.count("\n", 0, start) + 1
    line_end_no = source_text.count("\n", 0, max(start, end - 1)) + 1
    line_start = source_text.rfind("\n", 0, start) + 1
    line_end = source_text.find("\n", end)
    if line_end == -1:
        line_end = len(source_text)
    return line_start_no, line_end_no, source_text[line_start:line_end].rstrip("\n")


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _string_or_none(raw: Any) -> str | None:
    if isinstance(raw, (str, Path)) and str(raw):
        return str(raw)
    return None


def _replace_first(
    function_text: str,
    pattern: str,
    replacement_for_match: Any,
) -> str | None:
    match = re.search(pattern, function_text, re.MULTILINE)
    if match is None:
        return None
    replacement = replacement_for_match(match)
    return function_text[:match.start()] + replacement + function_text[match.end():]


def _patch_discovery_draw_col_product_local(function_text: str) -> str | None:
    return _replace_first(
        function_text,
        r"(?P<indent>[ \t]*)col_offset\s*=\s*y_spacing\s*\*\s*\(f32\)\s*col\s*;",
        lambda match: (
            f"{match.group('indent')}{{\n"
            f"{match.group('indent')}    f32 post_ceiling_col_factor;\n"
            f"{match.group('indent')}    f32 post_ceiling_col_product;\n"
            f"{match.group('indent')}    post_ceiling_col_factor = (f32) col;\n"
            f"{match.group('indent')}    post_ceiling_col_product = y_spacing * post_ceiling_col_factor;\n"
            f"{match.group('indent')}    col_offset = post_ceiling_col_product;\n"
            f"{match.group('indent')}}}"
        ),
    )


def _patch_discovery_draw_row_scale_split(function_text: str) -> str | None:
    patched = _replace_first(
        function_text,
        r"(?P<indent>[ \t]*)row_offset\s*=\s*y_offset\s*\*\s*\(f32\)\s*row\s*;",
        lambda match: (
            f"{match.group('indent')}{{\n"
            f"{match.group('indent')}    f32 post_ceiling_row_delta;\n"
            f"{match.group('indent')}    f32 post_ceiling_row_factor;\n"
            f"{match.group('indent')}    post_ceiling_row_delta = y_offset;\n"
            f"{match.group('indent')}    post_ceiling_row_factor = (f32) row;\n"
            f"{match.group('indent')}    row_offset = post_ceiling_row_delta * post_ceiling_row_factor;\n"
            f"{match.group('indent')}}}"
        ),
    )
    if patched is not None:
        return patched
    return _replace_first(
        function_text,
        (
            r"(?P<indent>[ \t]*)rowf\s*=\s*\(f32\)\s*row\s*;\s*\n"
            r"(?P=indent)[ \t]*row_offset\s*\*=\s*rowf\s*;"
        ),
        lambda match: (
            f"{match.group('indent')}{{\n"
            f"{match.group('indent')}    f32 post_ceiling_row_delta;\n"
            f"{match.group('indent')}    post_ceiling_row_delta = row_offset;\n"
            f"{match.group('indent')}    rowf = (f32) row;\n"
            f"{match.group('indent')}    row_offset = post_ceiling_row_delta * rowf;\n"
            f"{match.group('indent')}}}"
        ),
    )


def _patch_discovery_draw_digit_callarg_fsubs_temp(function_text: str) -> str | None:
    return _replace_first(
        function_text,
        (
            r"(?P<indent>[ \t]*)base\s*=\s*\(f32\)\s*digit\s*;\s*\n"
            r"(?P=indent)[ \t]*HSD_JObjReqAnimAll\(\s*jobj\s*,\s*base\s*\)\s*;"
        ),
        lambda match: (
            f"{match.group('indent')}{{\n"
            f"{match.group('indent')}    f32 post_ceiling_digit_source;\n"
            f"{match.group('indent')}    f32 post_ceiling_digit_arg;\n"
            f"{match.group('indent')}    post_ceiling_digit_source = (f32) digit;\n"
            f"{match.group('indent')}    post_ceiling_digit_arg = post_ceiling_digit_source - 0.0f;\n"
            f"{match.group('indent')}    base = post_ceiling_digit_arg;\n"
            f"{match.group('indent')}    HSD_JObjReqAnimAll(jobj, post_ceiling_digit_arg);\n"
            f"{match.group('indent')}}}"
        ),
    )


def _patch_discovery_sort_init_indexed_write(function_text: str) -> str | None:
    return _replace_first(
        function_text,
        (
            r"(?P<indent>[ \t]*)for \(n = 0; n < 0x78; n\+\+, dst_iter\+\+, tp\+\+\) \{\n"
            r"(?P=indent)[ \t]*\*dst_iter = \(u8\) n;\n"
            r"(?P=indent)[ \t]*\*tp = mnDiagram_SumNameKOs\(n & 0xFF\);\n"
            r"(?P=indent)\}"
        ),
        lambda match: (
            f"{match.group('indent')}for (n = 0; n < 0x78; n++) {{\n"
            f"{match.group('indent')}    dst[n] = (u8) n;\n"
            f"{match.group('indent')}    totals[n] = mnDiagram_SumNameKOs(n & 0xFF);\n"
            f"{match.group('indent')}}}"
        ),
    )


_SORT_INDEXED_BYTE_IF_PATTERN = (
    r"(?P<indent>[ \t]*)if \(\(GetNameText\(mnDiagram_804A076C\.sorted_names\[j\]\) != NULL\) &&\n"
    r"(?P=indent)[ \t]*\(\(totals\[mnDiagram_804A076C\.sorted_names\[\(?max_idx\)?\]\] <\n"
    r"(?P=indent)[ \t]*totals\[mnDiagram_804A076C\.sorted_names\[j\]\]\) \|\|\n"
    r"(?P=indent)[ \t]*\(\(GetNameText\(\n"
    r"(?P=indent)[ \t]*\(0, mnDiagram_804A076C\.sorted_names\[max_idx\]\)\) ==\n"
    r"(?P=indent)[ \t]*NULL\) &&\n"
    r"(?P=indent)[ \t]*\(GetNameText\(mnDiagram_804A076C\.sorted_names\[j\]\) != NULL\)\)\)\)\n"
    r"(?P=indent)\{\n"
    r"(?P=indent)[ \t]*max_idx = j;\n"
    r"(?P=indent)\}"
)


def _patch_discovery_sort_indexed_byte_cache(function_text: str) -> str | None:
    return _replace_first(
        function_text,
        _SORT_INDEXED_BYTE_IF_PATTERN,
        lambda match: (
            f"{match.group('indent')}{{\n"
            f"{match.group('indent')}    u8 post_ceiling_max_name;\n"
            f"{match.group('indent')}    u8 post_ceiling_j_name;\n"
            f"{match.group('indent')}    char* post_ceiling_max_text;\n"
            f"{match.group('indent')}    char* post_ceiling_j_text;\n"
            f"{match.group('indent')}    post_ceiling_max_name = mnDiagram_804A076C.sorted_names[max_idx];\n"
            f"{match.group('indent')}    post_ceiling_j_name = mnDiagram_804A076C.sorted_names[j];\n"
            f"{match.group('indent')}    post_ceiling_j_text = GetNameText(post_ceiling_j_name);\n"
            f"{match.group('indent')}    post_ceiling_max_text = GetNameText((0, post_ceiling_max_name));\n"
            f"{match.group('indent')}    if ((post_ceiling_j_text != NULL) &&\n"
            f"{match.group('indent')}        ((totals[post_ceiling_max_name] < totals[post_ceiling_j_name]) ||\n"
            f"{match.group('indent')}         ((post_ceiling_max_text == NULL) &&\n"
            f"{match.group('indent')}          (post_ceiling_j_text != NULL))))\n"
            f"{match.group('indent')}    {{\n"
            f"{match.group('indent')}        max_idx = j;\n"
            f"{match.group('indent')}    }}\n"
            f"{match.group('indent')}}}"
        ),
    )


def _patch_discovery_sort_call_return_copy_local(function_text: str) -> str | None:
    return _replace_first(
        function_text,
        _SORT_INDEXED_BYTE_IF_PATTERN,
        lambda match: (
            f"{match.group('indent')}{{\n"
            f"{match.group('indent')}    u8 post_ceiling_max_name;\n"
            f"{match.group('indent')}    u8 post_ceiling_j_name;\n"
            f"{match.group('indent')}    char* post_ceiling_max_text;\n"
            f"{match.group('indent')}    char* post_ceiling_j_text;\n"
            f"{match.group('indent')}    char* post_ceiling_j_text_copy;\n"
            f"{match.group('indent')}    post_ceiling_max_name = mnDiagram_804A076C.sorted_names[max_idx];\n"
            f"{match.group('indent')}    post_ceiling_j_name = mnDiagram_804A076C.sorted_names[j];\n"
            f"{match.group('indent')}    post_ceiling_j_text = GetNameText(post_ceiling_j_name);\n"
            f"{match.group('indent')}    post_ceiling_j_text_copy = post_ceiling_j_text;\n"
            f"{match.group('indent')}    post_ceiling_max_text = GetNameText((0, post_ceiling_max_name));\n"
            f"{match.group('indent')}    if ((post_ceiling_j_text_copy != NULL) &&\n"
            f"{match.group('indent')}        ((totals[post_ceiling_max_name] < totals[post_ceiling_j_name]) ||\n"
            f"{match.group('indent')}         ((post_ceiling_max_text == NULL) &&\n"
            f"{match.group('indent')}          (post_ceiling_j_text_copy != NULL))))\n"
            f"{match.group('indent')}    {{\n"
            f"{match.group('indent')}        max_idx = j;\n"
            f"{match.group('indent')}    }}\n"
            f"{match.group('indent')}}}"
        ),
    )


def _patch_discovery_sort_swap_slot_lvalue(function_text: str) -> str | None:
    return _replace_first(
        function_text,
        (
            r"(?P<indent>[ \t]*)u8\* p = &assets->sorted_fighters\[max_idx\];\n"
            r"(?P=indent)[ \t]*u8 temp = \*\(p \+= sizeof\(mnDiagram_804A0750_t\)\);"
        ),
        lambda match: (
            f"{match.group('indent')}u8* p = &assets->sorted_fighters[max_idx];\n"
            f"{match.group('indent')}u8* post_ceiling_selected_name_slot = assets->sorted_names + max_idx;\n"
            f"{match.group('indent')}u8 temp = *post_ceiling_selected_name_slot;\n"
            f"{match.group('indent')}p = post_ceiling_selected_name_slot;"
        ),
    )


def _post_ceiling_force_conflict_summary(
    *,
    function: str,
    source_function: str | None,
    terminal_summary: Mapping[str, Any],
    score_rows: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    force_conflicts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summary = _post_ceiling_final_synthesis_summary(
        function=function,
        source_function=source_function,
        terminal_summary=terminal_summary,
        score_rows=score_rows,
        evidence=evidence,
        force_conflicts=force_conflicts,
    )
    summary["kind"] = FORCE_CONFLICT_TERMINAL_KIND
    summary["terminal_blocker"] = FORCE_CONFLICT_BLOCKER
    summary["terminal_reason"] = FORCE_CONFLICT_TERMINAL_REASON
    return summary


def _residual_blocker_targets(
    score_rows: Sequence[Mapping[str, Any]],
    final_force_phys: Mapping[str, int],
) -> list[dict[str, Any]]:
    residual: list[dict[str, Any]] = []
    for virtual, expected in sorted(
        _normalized_int_mapping(final_force_phys).items(),
        key=lambda item: int(item[0]),
    ):
        parsed_virtual = _int_or_none(virtual)
        if parsed_virtual is None:
            continue
        row = _first_score_virtual_row(
            score_rows,
            virtual=parsed_virtual,
        )
        actual = _int_or_none(row.get("actual")) if isinstance(row, Mapping) else None
        matched = bool(row.get("matched")) if isinstance(row, Mapping) else False
        if actual is not None and actual == expected:
            matched = True
        if matched:
            continue
        residual.append(
            {
                "virtual": parsed_virtual,
                "expected": expected,
                "actual": actual,
                "matched": False,
                "score_source": (
                    row.get("score_source")
                    if isinstance(row, Mapping)
                    else None
                ),
            }
        )
    return residual


def _first_score_virtual_row(
    score_rows: Sequence[Mapping[str, Any]],
    *,
    virtual: int,
) -> Mapping[str, Any] | None:
    key = str(virtual)
    for score_row in score_rows:
        if not isinstance(score_row, Mapping):
            continue
        for score_source in ("target_score", "expression_score"):
            score = _nested_mapping(score_row, (score_source,))
            if not isinstance(score, Mapping):
                continue
            virtuals = score.get("virtuals")
            if not isinstance(virtuals, Mapping):
                continue
            row = virtuals.get(key)
            if isinstance(row, Mapping):
                out = dict(row)
                out["score_source"] = score_source
                return out
    return None


def _target_anchors_from_force_phys(force_phys: Mapping[str, int]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for virtual, expected in sorted(force_phys.items(), key=lambda item: int(item[0])):
        anchors.append(
            {
                "virtual": _int_or_str(virtual),
                "baseline_virtual": _int_or_none(virtual),
                "name": f"ig{virtual}",
                "expression": None,
                "expected": expected,
                "actual": None,
                "matched": False,
            }
        )
    return anchors


def _target_score_counts(
    target_score: Mapping[str, Any] | None,
) -> tuple[int | None, int | None, int | None]:
    if not isinstance(target_score, Mapping):
        return None, None, None
    matched = _int_or_none(target_score.get("matched"))
    targeted = _int_or_none(target_score.get("targeted"))
    virtuals = target_score.get("virtuals")
    if isinstance(virtuals, Mapping):
        matched_count = 0
        targeted_count = 0
        for row in virtuals.values():
            if not isinstance(row, Mapping):
                continue
            expected = _int_or_none(row.get("expected"))
            actual = _int_or_none(row.get("actual"))
            if expected is None:
                continue
            targeted_count += 1
            if row.get("matched") is True or actual == expected:
                matched_count += 1
        if targeted is None:
            targeted = targeted_count
        if matched is None:
            matched = matched_count
    distance = _int_or_none(target_score.get("virtual_distance"))
    if distance is None and targeted is not None and matched is not None:
        distance = max(targeted - matched, 0)
    return matched, targeted, distance


def _validation_metadata(
    evidence: Mapping[str, Any],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    function = str(options.get("function") or "")
    sort_profile = _is_sort_profile(function)
    metadata: dict[str, Any] = {
        "requires_expression_score_validation": not sort_profile,
        "requires_target_score_validation": sort_profile,
        "target_anchors": evidence.get("target_anchors", []),
        "final_force_phys": evidence.get("final_force_phys", {}),
        "register_class": "gpr" if sort_profile else "fpr",
    }
    for key, value in options.items():
        if value is not None:
            metadata[key] = str(value)
    metadata["score_source_command_hint"] = _score_command_hint(metadata)
    return metadata


def _score_command_hint(metadata: Mapping[str, Any]) -> str:
    parts = [
        "melee-agent debug target score-source {candidate_path}",
        f"-f {metadata.get('function') or metadata.get('source_function') or '<function>'}",
    ]
    if metadata.get("target"):
        parts.append(f"--target {metadata['target']}")
    if metadata.get("cflags_from"):
        parts.append(f"--cflags-from {metadata['cflags_from']}")
    if metadata.get("expression_baseline"):
        parts.append(f"--expression-baseline {metadata['expression_baseline']}")
    if metadata.get("expression_source"):
        parts.append(f"--expression-source {metadata['expression_source']}")
    reg_class = metadata.get("register_class") or "fpr"
    if metadata.get("requires_expression_score_validation", True):
        parts.append(f"--expression-reg-class {reg_class}")
    else:
        parts.append(f"--expression-reg-class {reg_class}")
    parts.extend(["--retain-pcdump", "--json"])
    return " ".join(parts)


def _validation_hint(*, function: str) -> str:
    if _is_sort_profile(function):
        return (
            "Score each candidate with debug target score-source using the Sort "
            f"IG34/IG44 GPR force targets for {function}; retain .pcdump and score JSON."
        )
    return (
        "Score each candidate with debug target score-source using the Draw "
        f"force/expression targets for {function}; retain .pcdump and score JSON."
    )


def _classify_score_payload(score_payload: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    expression_score = _first_mapping_by_key(score_payload, "expression_score")
    target_score = _first_mapping_by_key(score_payload, "target_score")
    structural = _first_mapping_by_key(score_payload, "structural_guard")
    candidate_id = _candidate_id(score_payload, index=index)
    matched = _int_or_none(
        expression_score.get("matched") if isinstance(expression_score, Mapping) else None
    )
    targeted = _int_or_none(
        expression_score.get("targeted") if isinstance(expression_score, Mapping) else None
    )
    target_matched, target_targeted, target_virtual_distance = _target_score_counts(
        target_score
    )
    match_percent = _float_or_none(score_payload.get("match_percent"))
    if match_percent is None:
        match_percent = _float_or_none(score_payload.get("percent"))

    if matched is not None and matched > 0:
        classification = "expression-progress"
    elif target_matched is not None and target_matched > 0:
        classification = "target-progress"
    elif _structural_preserving(score_payload, structural):
        classification = "structural-preserving"
    elif expression_score is None and target_score is None:
        classification = "unscoreable"
    else:
        classification = "recoverable-downhill"
    return {
        "candidate_id": candidate_id,
        "pcdump_path": score_payload.get("pcdump_path"),
        "source_file": score_payload.get("source_file"),
        "source_retained": score_payload.get("source_retained"),
        "path": score_payload.get("path"),
        "classification": classification,
        "expression_matched": matched,
        "expression_targeted": targeted,
        "expression_virtual_distance": _int_or_none(
            expression_score.get("virtual_distance")
            if isinstance(expression_score, Mapping)
            else None
        ),
        "target_matched": target_matched,
        "target_targeted": target_targeted,
        "target_virtual_distance": target_virtual_distance,
        "score_matched": matched if matched is not None else target_matched,
        "score_targeted": targeted if targeted is not None else target_targeted,
        "score_virtual_distance": (
            _int_or_none(expression_score.get("virtual_distance"))
            if isinstance(expression_score, Mapping)
            else target_virtual_distance
        ),
        "match_percent": match_percent,
        "structural_preserving": _structural_preserving(score_payload, structural),
        "expression_score": dict(expression_score) if isinstance(expression_score, Mapping) else None,
        "target_score": dict(target_score) if isinstance(target_score, Mapping) else None,
        "validation_metadata": (
            dict(score_payload.get("validation_metadata"))
            if isinstance(score_payload.get("validation_metadata"), Mapping)
            else None
        ),
        "suppressed_families": list(_string_items(score_payload.get("suppressed_families"))),
    }


def _structural_preserving(
    score_payload: Mapping[str, Any],
    structural: Mapping[str, Any] | None,
) -> bool:
    if isinstance(structural, Mapping):
        if structural.get("accepted") is True or structural.get("ok") is True:
            return True
        status = str(structural.get("status") or "").lower()
        if status in {"accepted", "ok", "normalized-structural-match"}:
            return True
    for key in ("status", "match_status", "classification"):
        value = str(score_payload.get(key) or "").lower()
        if "normalized-structural-match" in value or value == "structural-preserving":
            return True
    return False


def _terminal_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    function: str | None = None,
) -> dict[str, Any]:
    best = _best_score_row(rows)
    terminal_kind = _terminal_kind(function)
    return {
        "status": "terminal",
        "kind": terminal_kind,
        "terminal_blocker": TERMINAL_BLOCKER,
        "terminal_reason": _terminal_reason(function),
        "family_id": SUPPRESSION_FAMILY,
        "suppression_family": SUPPRESSION_FAMILY,
        "candidate_count": len(rows),
        "scored_count": len(rows),
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_expression_matched": best.get("expression_matched") if best else None,
        "best_expression_targeted": best.get("expression_targeted") if best else None,
        "best_expression_virtual_distance": (
            best.get("expression_virtual_distance") if best else None
        ),
        "best_target_matched": best.get("target_matched") if best else None,
        "best_target_targeted": best.get("target_targeted") if best else None,
        "best_target_virtual_distance": (
            best.get("target_virtual_distance") if best else None
        ),
    }


def _best_score_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("score_matched") or row.get("expression_matched") or 0),
            int(
                row.get("score_virtual_distance")
                or row.get("expression_virtual_distance")
                or 9999
            ),
            str(row.get("candidate_id") or ""),
        ),
    )[0]


def _source_candidates_from_retained_frontiers(
    retained_frontiers: Mapping[str, Any] | None,
    *,
    function: str,
) -> list[Any]:
    if not isinstance(retained_frontiers, Mapping):
        return []
    out: list[Any] = []
    functions = retained_frontiers.get("functions")
    if not isinstance(functions, Sequence) or isinstance(functions, (str, bytes)):
        return out
    for entry in functions:
        if not isinstance(entry, Mapping) or entry.get("function") != function:
            continue
        for key in ("frontiers", "terminal_frontiers"):
            rows = entry.get(key)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            for row in rows:
                if isinstance(row, Mapping):
                    out.extend(_retained_candidate_paths(row))
    return out


def _retained_candidate_paths(payload: Any) -> list[Any]:
    out: list[Any] = []
    if isinstance(payload, Mapping):
        for key in ("source_file", "source_retained", "source", "path"):
            if payload.get(key) is not None:
                out.append(payload[key])
        for value in payload.values():
            out.extend(_retained_candidate_paths(value))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            out.extend(_retained_candidate_paths(item))
    return out


def _resolve_existing_path(path: Path, *, repo_root: Path) -> Path:
    expanded = path.expanduser()
    candidates = [expanded]
    if not expanded.is_absolute():
        candidates.append(Path.cwd() / expanded)
        candidates.append(repo_root / expanded)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(f"source file not found: {path}")


def _nested_get(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _nested_mapping(payload: Mapping[str, Any], keys: Sequence[str]) -> Mapping[str, Any] | None:
    value = _nested_get(payload, keys)
    return value if isinstance(value, Mapping) else None


def _first_mapping_by_key(payload: Any, key: str) -> Mapping[str, Any] | None:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
        for child in payload.values():
            found = _first_mapping_by_key(child, key)
            if found is not None:
                return found
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for child in payload:
            found = _first_mapping_by_key(child, key)
            if found is not None:
                return found
    return None


def _candidate_id(score_payload: Mapping[str, Any], *, index: int) -> str:
    for key in ("candidate_id", "id", "probe_id"):
        value = score_payload.get(key)
        if value:
            return str(value)
    path = (
        score_payload.get("path")
        or score_payload.get("source_file")
        or score_payload.get("pcdump_path")
    )
    if path:
        stem = Path(str(path)).name
        for suffix in (
            ".source-fn.pcdump.txt",
            ".pcdump.txt",
            ".source-fn.score.json",
            ".score.json",
            ".c",
        ):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        return stem
    return f"score-{index + 1}"


def _string_items(raw: Any) -> list[str]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [str(item) for item in raw if item]
    return [str(raw)] if raw else []


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int_or_str(value: Any) -> int | str:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else str(value)
