"""Post-source-ceiling backend/codegen next-axis diagnostics.

This module is diagnostic-only. It consumes terminal source-model artifacts and
normalizes the remaining register evidence into a backend/codegen handoff
without re-emitting another source-family continuation.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


DISCOVERY_KIND = "post-source-model-ceiling-next-axis-discovery"
FAMILY_ID = "post-source-model-ceiling-backend-codegen-axis"
TERMINAL_REASON = (
    "post-source-model-ceiling-next-axis-exhausted/no-modeled-non-source-axis"
)
TERMINAL_BLOCKER = "no-modeled-non-source-axis"
DRAW_FUNCTION = "mnDiagram_DrawCellNumber"
SORT_FUNCTION = "mnDiagram_SortNamesByKOs"


class PostSourceCeilingAxisError(ValueError):
    """Raised when a post-source-ceiling artifact is malformed."""


class PostSourceCeilingAxisDiscovery:
    """Discover backend/codegen handoff axes after source-family exhaustion."""

    def discover(
        self,
        *,
        function: str,
        source_model: Mapping[str, Any] | None = None,
        retained_frontiers: Mapping[str, Any] | None = None,
        allocator_ceiling: Mapping[str, Any] | None = None,
        post_source_context: Mapping[str, Any] | None = None,
        continuation: Mapping[str, Any] | None = None,
        first_divergence: Mapping[str, Any] | None = None,
        simplify_order: Mapping[str, Any] | None = None,
        bank: str = "auto",
    ) -> dict[str, Any]:
        raw_artifacts = [
            artifact
            for artifact in (
                post_source_context,
                source_model,
                continuation,
                retained_frontiers,
                allocator_ceiling,
            )
            if isinstance(artifact, Mapping)
        ]
        artifacts = _scope_artifacts(function, raw_artifacts)
        if not artifacts:
            return _not_applicable(
                function,
                "empty-input" if not raw_artifacts else "source-ceiling-not-terminal",
            )
        if not _has_terminal_source_ceiling(artifacts):
            return _not_applicable(function, "source-ceiling-not-terminal")

        register_class = _resolve_register_class(
            function=function,
            artifacts=artifacts,
            bank=bank,
        )
        rows = _retained_rows(artifacts)
        anchors = _anchor_evidence(rows, register_class=register_class)
        proof = {
            "status": "terminal-source-ceiling",
            "closed_source_families": _closed_source_families(artifacts),
            "terminal_reasons": _terminal_reasons(artifacts),
            "exhausted_dimensions": _exhausted_dimensions(artifacts),
            "artifact_kinds": _artifact_kinds(artifacts),
        }
        ranked_axes = _ranked_axes(
            function=function,
            register_class=register_class,
            rows=rows,
            anchors=anchors,
        )
        payload = {
            "kind": DISCOVERY_KIND,
            "status": "terminal",
            "family_id": FAMILY_ID,
            "function": function,
            "register_class": register_class,
            "terminal_reason": TERMINAL_REASON,
            "terminal_blocker": TERMINAL_BLOCKER,
            "source_ceiling_proof": proof,
            "anchor_evidence": anchors,
            "ranked_axes": ranked_axes,
            "modeled_non_source_axis_count": 0,
            "terminal_proof": {
                "kind": "no-modeled-non-source-axis-proof",
                "terminal_reason": TERMINAL_REASON,
                "preserved_evidence_count": len(rows),
                "diagnostic_axis_count": len(ranked_axes),
            },
        }
        repair_lanes = _source_repair_lanes(
            function=function,
            register_class=register_class,
            first_divergence=first_divergence,
            simplify_order=simplify_order,
            anchors=anchors,
        )
        if repair_lanes:
            payload["source_repair_lanes"] = repair_lanes
        return payload


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PostSourceCeilingAxisError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PostSourceCeilingAxisError(
            f"could not parse JSON artifact {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PostSourceCeilingAxisError(f"artifact is not a JSON object: {path}")
    return payload


def render_text(payload: Mapping[str, Any]) -> str:
    lines = [
        f"Function: {payload.get('function')}",
        f"Status:   {payload.get('status')}",
    ]
    if payload.get("reason"):
        lines.append(f"Reason:   {payload.get('reason')}")
        return "\n".join(lines)
    lines.extend(
        [
            f"Bank:     {payload.get('register_class')}",
            f"Terminal: {payload.get('terminal_reason')}",
        ]
    )
    proof = payload.get("source_ceiling_proof")
    if isinstance(proof, Mapping):
        families = proof.get("closed_source_families")
        if isinstance(families, list) and families:
            lines.append("Closed source families:")
            lines.extend(f"  - {family}" for family in families)
    axes = payload.get("ranked_axes")
    if isinstance(axes, list) and axes:
        lines.append("Ranked backend/codegen diagnostics:")
        for axis in axes:
            if not isinstance(axis, Mapping):
                continue
            lines.append(
                f"  {axis.get('rank')}. {axis.get('axis_id')} "
                f"({axis.get('axis_class')})"
            )
            rationale = axis.get("rationale")
            if isinstance(rationale, str) and rationale:
                lines.append(f"     {rationale}")
    return "\n".join(lines)


def _not_applicable(function: str, reason: str) -> dict[str, Any]:
    return {
        "kind": DISCOVERY_KIND,
        "status": "not-applicable",
        "family_id": FAMILY_ID,
        "function": function,
        "reason": reason,
    }


def _scope_artifacts(
    function: str,
    artifacts: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    scoped: list[Mapping[str, Any]] = []
    for artifact in artifacts:
        scoped_artifact = _scope_artifact(function, artifact)
        if scoped_artifact is not None:
            scoped.append(scoped_artifact)
    return scoped


def _scope_artifact(
    function: str,
    artifact: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    top_function = _str(artifact.get("function"))
    functions = artifact.get("functions")
    if isinstance(functions, list):
        matching = [
            dict(entry)
            for entry in functions
            if isinstance(entry, Mapping) and entry.get("function") == function
        ]
        if matching:
            scoped = dict(artifact)
            scoped["functions"] = matching
            return scoped
        if top_function == function:
            scoped = dict(artifact)
            scoped["functions"] = []
            return scoped
        return None
    if top_function is not None and top_function != function:
        return None
    return artifact


def _has_terminal_source_ceiling(artifacts: Sequence[Mapping[str, Any]]) -> bool:
    for mapping in _walk_mappings(artifacts):
        if mapping.get("status") in {
            "terminal",
            "unsupported-source-family",
            "all-known-frontiers-exhausted",
            "practical-ceiling",
            "terminal-current-source-shape-ceiling",
            "complete",
        }:
            return True
        if mapping.get("terminal") is True:
            return True
        if _str(mapping.get("next_unsupported_source_family")):
            return True
        reason = _str(mapping.get("reason"))
        if reason == "no-modeled-source-actionable-frontiers-remain":
            return True
    return False


def _resolve_register_class(
    *,
    function: str,
    artifacts: Sequence[Mapping[str, Any]],
    bank: str,
) -> str:
    if bank in {"gpr", "fpr"}:
        return bank
    if bank != "auto":
        raise PostSourceCeilingAxisError("--bank must be one of auto, gpr, or fpr")
    for mapping in _walk_mappings(artifacts):
        for key in ("target_score", "expression_score"):
            score = mapping.get(key)
            if isinstance(score, Mapping):
                register_class = _str(score.get("register_class"))
                if register_class in {"gpr", "fpr"}:
                    return register_class
    for mapping in _walk_mappings(artifacts):
        kind = " ".join(
            _str(mapping.get(key)) or ""
            for key in ("kind", "terminal_reason", "next_unsupported_source_family")
        )
        lowered = kind.lower()
        if "fpr" in lowered:
            return "fpr"
        if "gpr" in lowered:
            return "gpr"
    if function == DRAW_FUNCTION:
        return "fpr"
    return "gpr"


def _retained_rows(artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mapping in _walk_mappings(artifacts):
        for key in (
            "retained_evidence",
            "candidate_scores",
            "retained_scored_probes",
            "ranked_retained_c_probes",
            "ranked_retained_candidates",
            "retained_candidates",
        ):
            value = mapping.get(key)
            if not isinstance(value, list):
                continue
            for row in value:
                if isinstance(row, Mapping):
                    rows.append(dict(row))
    return _dedupe_rows(rows)


def _anchor_evidence(
    rows: Sequence[Mapping[str, Any]],
    *,
    register_class: str,
) -> dict[str, Any]:
    target_anchors = _anchors_from_score(rows, "target_score", register_class)
    expression_anchors = _anchors_from_score(rows, "expression_score", register_class)
    return {
        "target_anchors": target_anchors,
        "expression_anchors": expression_anchors,
        "retained_score_rows": [dict(row) for row in rows],
        "retained_candidates": [
            _candidate_summary(row)
            for row in rows
            if _candidate_summary(row)
        ],
    }


def _anchors_from_score(
    rows: Sequence[Mapping[str, Any]],
    score_key: str,
    register_class: str,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for row in rows:
        score = row.get(score_key)
        if not isinstance(score, Mapping):
            continue
        score_class = _str(score.get("register_class"))
        if score_class not in {None, "", register_class}:
            continue
        virtuals = score.get("virtuals")
        if not isinstance(virtuals, Mapping):
            continue
        for virtual, detail in virtuals.items():
            if not isinstance(detail, Mapping):
                continue
            anchor = {
                "virtual": str(virtual),
                "expected": detail.get("expected"),
                "actual": detail.get("actual"),
                "matched": detail.get("matched"),
                "register_class": register_class,
                "score": score_key,
                "candidate_id": row.get("candidate_id"),
                "dimension_id": row.get("dimension_id"),
                "pcdump_path": row.get("pcdump_path"),
                "source_retained": row.get("source_retained"),
            }
            anchors.append({k: v for k, v in anchor.items() if v is not None})
    return _dedupe_dicts(
        anchors,
        keys=(
            "virtual",
            "expected",
            "actual",
            "score",
            "candidate_id",
            "pcdump_path",
        ),
    )


def _candidate_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "candidate_id": row.get("candidate_id"),
        "dimension_id": row.get("dimension_id"),
        "pcdump_path": row.get("pcdump_path"),
        "source_retained": row.get("source_retained"),
        "source_hunks": row.get("source_hunks"),
        "structural_guard": row.get("structural_guard"),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _closed_source_families(artifacts: Sequence[Mapping[str, Any]]) -> list[str]:
    families: list[str] = []
    for mapping in _walk_mappings(artifacts):
        for key in (
            "next_unsupported_source_family",
            "trigger_family",
            "family_id",
            "suppression_family",
        ):
            value = _str(mapping.get(key))
            if value and _looks_source_family(value):
                families.append(value)
    return _dedupe_strings(families)


def _terminal_reasons(artifacts: Sequence[Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for mapping in _walk_mappings(artifacts):
        for key in ("terminal_reason", "terminal_blocker", "reason"):
            value = _str(mapping.get(key))
            if value and value not in {
                "no-modeled-source-actionable-frontiers-remain",
                "transform-family-exhausted",
            }:
                reasons.append(value)
    return _dedupe_strings(reasons)


def _exhausted_dimensions(artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mapping in _walk_mappings(artifacts):
        dimension = _str(mapping.get("exhausted_source_dimension"))
        if dimension:
            rows.append({"dimension_id": dimension})
        value = mapping.get("exhausted_dimensions")
        if isinstance(value, list):
            for row in value:
                if isinstance(row, str):
                    rows.append({"dimension_id": row})
                elif isinstance(row, Mapping):
                    dimension_id = _str(row.get("dimension_id") or row.get("id"))
                    if dimension_id:
                        rows.append({"dimension_id": dimension_id})
        dimension = _str(mapping.get("dimension_id"))
        if dimension and mapping.get("status") in {
            "terminal",
            "scored-terminal",
            "exhausted",
        }:
            rows.append({"dimension_id": dimension})
    return _dedupe_dicts(rows, keys=("dimension_id",))


def _artifact_kinds(artifacts: Sequence[Mapping[str, Any]]) -> list[str]:
    kinds = [
        kind
        for artifact in artifacts
        if (kind := _str(artifact.get("kind"))) is not None
    ]
    return _dedupe_strings(kinds)


def _ranked_axes(
    *,
    function: str,
    register_class: str,
    rows: Sequence[Mapping[str, Any]],
    anchors: Mapping[str, Any],
) -> list[dict[str, Any]]:
    row = _representative_row(rows)
    if register_class == "fpr":
        specs = [
            (
                "fpr-expression-anchor-allocation-coupling",
                "Check whether the remaining FPR expression anchors are coupled by backend allocation rather than source ownership.",
            ),
            (
                "fpr-helper-boundary-materialization",
                "Inspect helper-boundary materialization and scheduling around the retained expression anchors.",
            ),
            (
                "fpr-force-phys-coloring-conflict",
                "Probe whether force-phys assignments conflict after source families are exhausted.",
            ),
        ]
    else:
        specs = [
            (
                "gpr-case-c-live-range-allocation",
                "Check retained Case-C live-range allocation for the remaining protected GPR targets.",
            ),
            (
                "gpr-selection-swap-pointer-materialization",
                "Inspect backend materialization of selection/swap pointer values after source linkage is exhausted.",
            ),
            (
                "gpr-force-phys-coloring-conflict",
                "Probe whether force-phys assignments conflict under the retained GPR target anchors.",
            ),
        ]
    return [
        {
            "rank": index,
            "axis_id": axis_id,
            "axis_class": "backend-codegen",
            "confidence": "diagnostic",
            "rationale": rationale,
            "evidence": {
                key: value
                for key, value in {
                    "candidate_id": row.get("candidate_id") if row else None,
                    "dimension_id": row.get("dimension_id") if row else None,
                    "pcdump_path": row.get("pcdump_path") if row else None,
                    "source_retained": row.get("source_retained") if row else None,
                    "anchor_count": len(
                        anchors.get("expression_anchors")
                        if register_class == "fpr"
                        else anchors.get("target_anchors")
                        or []
                    ),
                }.items()
                if value is not None
            },
            "diagnostics": _diagnostics(function=function, row=row),
        }
        for index, (axis_id, rationale) in enumerate(specs, start=1)
    ]


def _diagnostics(
    *,
    function: str,
    row: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    pcdump = _str(row.get("pcdump_path")) if row else None
    first_divergence = [
        "melee-agent",
        "debug",
        "inspect",
        "first-divergence",
    ]
    if pcdump:
        first_divergence.append(pcdump)
    first_divergence.extend(["--function", function])
    force_phys = _force_phys_from_row(row)
    if force_phys:
        first_divergence.extend(["--force-phys", force_phys])
    register_class = _row_register_class(row)
    class_id = "1" if register_class == "fpr" else "0"
    first_divergence.extend(["--class", class_id])
    first_divergence.extend(["--source", "--json"])
    diagnostics = [
        {
            "tool": "first-divergence",
            "command_hint": shlex.join(first_divergence),
        }
    ]
    if pcdump and force_phys:
        setup = [
            "melee-agent",
            "debug",
            "permute",
            "setup-simplify-order-scorer",
            "--function",
            function,
            "--scorer-mode",
            "force-phys",
            "--baseline-dump",
            pcdump,
            "--force-phys",
            force_phys,
            "--class",
            class_id,
        ]
        diagnostics.append(
            {
                "tool": "force-phys-setup",
                "command_hint": shlex.join(setup),
                "force_phys_csv": force_phys,
                "class_id": class_id,
                "baseline_dump": pcdump,
                "requires": "permuter candidate object with pcdump sidecar",
            }
        )
    return diagnostics


def _source_repair_lanes(
    *,
    function: str,
    register_class: str,
    first_divergence: Mapping[str, Any] | None,
    simplify_order: Mapping[str, Any] | None,
    anchors: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if register_class != "fpr" or not isinstance(first_divergence, Mapping):
        return []
    fact = first_divergence.get("fact")
    source = first_divergence.get("source")
    if not isinstance(fact, Mapping) or not isinstance(source, Mapping):
        return []
    expression = _str(source.get("source_expression"))
    if (
        fact.get("case") != "C"
        or source.get("source_kind") != "fpr-temp"
        or expression is None
        or not expression.startswith("lfd ")
    ):
        return []
    constant = _constant_load_owner(expression)
    if constant is None:
        return []
    candidate_spans = source.get("candidate_spans")
    source_line = source.get("source_line")
    terminal = source_line is None and not candidate_spans
    lane = {
        "kind": "post-source-ceiling-fpr-constant-load-source-repair",
        "function": function,
        "case": fact.get("case"),
        "ig_idx": fact.get("ig_idx"),
        "status": "terminal-blocker" if terminal else "source-attributed",
        "source_kind": source.get("source_kind"),
        "source_expression": expression,
        "source_file": source.get("source_file"),
        "source_line": source_line,
        "source_col": source.get("source_col"),
        "constant_load_owner": constant,
        "expression_anchors": anchors.get("expression_anchors") or [],
        "target_anchors": anchors.get("target_anchors") or [],
        "stop_condition": (
            "bounded probes improve retained FPR anchors, or the pcode-only "
            "constant load is terminally classified as unmapped"
        ),
    }
    if terminal:
        lane["terminal_blocker"] = "pcode-only-fpr-constant-load-owner-unmapped"
        lane["reason"] = (
            "first-divergence identified an FPR pcode constant load but did "
            "not provide a source line, variable, or candidate span to mutate"
        )
    if isinstance(simplify_order, Mapping):
        lane["bounded_probe_result"] = {
            key: simplify_order.get(key)
            for key in (
                "status",
                "terminal_blocker",
                "progress_count",
                "candidate_count",
            )
            if key in simplify_order
        }
    return [lane]


def _constant_load_owner(expression: str) -> dict[str, Any] | None:
    parts = expression.split(None, 1)
    if len(parts) != 2 or parts[0] != "lfd":
        return None
    operands = [part.strip() for part in parts[1].split(",", 1)]
    if len(operands) != 2:
        return None
    target, address = operands
    if not target.startswith("f"):
        return None
    return {
        "opcode": "lfd",
        "target_register": target,
        "address_expression": address,
        "owner_status": "unmapped-pcode-constant-load",
    }


def _force_phys_from_row(row: Mapping[str, Any] | None) -> str | None:
    if row is None:
        return None
    score = row.get("target_score")
    if not isinstance(score, Mapping):
        score = row.get("expression_score")
    if not isinstance(score, Mapping):
        return None
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return None
    parts: list[str] = []
    for virtual, detail in virtuals.items():
        if not isinstance(detail, Mapping):
            continue
        expected = detail.get("expected")
        if expected is None:
            continue
        parts.append(f"{virtual}:{expected}")
    return ",".join(parts) if parts else None


def _row_register_class(row: Mapping[str, Any] | None) -> str | None:
    if row is None:
        return None
    for key in ("target_score", "expression_score"):
        score = row.get(key)
        if not isinstance(score, Mapping):
            continue
        register_class = _str(score.get("register_class"))
        if register_class in {"gpr", "fpr"}:
            return register_class
    return None


def _representative_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for row in rows:
        if row.get("pcdump_path") or row.get("source_retained"):
            return row
    return rows[0] if rows else None


def _looks_source_family(value: str) -> bool:
    lowered = value.lower()
    return (
        "source" in lowered
        or lowered.startswith("draw-")
        or lowered.startswith("sort-")
        or lowered.startswith("post-ceiling")
        or lowered.startswith("post-meta")
    )


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list) or isinstance(value, tuple):
        for child in value:
            yield from _walk_mappings(child)


def _dedupe_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = "|".join(
            str(row.get(field) or "")
            for field in ("candidate_id", "dimension_id", "pcdump_path")
        )
        if key == "||":
            key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _dedupe_dicts(
    rows: Sequence[Mapping[str, Any]],
    *,
    keys: Sequence[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = tuple(row.get(field) for field in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
