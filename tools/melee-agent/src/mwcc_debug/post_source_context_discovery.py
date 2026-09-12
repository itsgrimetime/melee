"""Post-source-context next-dimension discovery for retained Draw FPR ceilings."""

from __future__ import annotations

import json
import math
import shlex
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


DISCOVERY_KIND = "post-source-context-fpr-next-dimension-discovery"
DISCOVERY_FAMILY = "post-source-context-fpr-ceiling-next-dimension"
DRAW_FUNCTION = "mnDiagram_DrawCellNumber"
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION = (
    "draw-loop-body-callsite-and-object-base-lifetime-source-context"
)
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-loop-body-callsite-"
    "and-object-base-lifetime-source-context"
)
DRAW_POST_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-source-context-whole-function-fpr-source-model"
)
DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY = (
    "draw-next-unsupported-source-dimension-after-loop-body-callsite-and-"
    "object-base-lifetime-source-context"
)
DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_MODEL = (
    "Draw post-source-context whole-function FPR source model spanning preloop "
    "object/base/data ownership plus loop callsite, translate, animation, and "
    "add-child ownership after loop-body callsite/object-base lifetime "
    "source-context exhaustion."
)
DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-source-context-"
    "whole-function-fpr-source-model"
)
DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-source-context whole-function FPR source-model synthesis "
    "exhausted bounded preloop object/base/data ownership plus loop digit "
    "object, animation, translate, and add-child ownership probes without "
    "improving the retained target/real-expression floor. No further modeled "
    "source-actionable Draw family remains after this whole-function layer."
)
DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS = (
    "draw-coupled-post-meta-fpr-expression-lifetime"
)
DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL = (
    "Draw coupled post-meta FPR expression lifetime/materialization across "
    "col_offset product, row_offset fsubs, and digit-animation fsubs/callarg temp."
)
DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS = "unsupported-source-family"
DRAW_POST_WHOLE_FUNCTION_TERMINAL_REASON = (
    "draw-post-source-context-whole-function-fpr-source-model-exhausted/"
    "no-floor-improvement"
)
DRAW_POST_SOURCE_CONTEXT_DEFAULT_FLOOR = {"target": 1, "expression": 1}
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery"
)
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery-"
    "exhausted/no-anchor-recovery"
)
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery/"
    "no-source-actionable-anchor-recovery"
)
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-product-translate-"
    "stack-clean-no-anchor-recovery"
)
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL = (
    "Draw post-product/translate stack-clean/no-anchor recovery exhausted "
    "bounded row-delta, digit fsubs, col-product owner-transfer, and "
    "frame-clean owner-prune probes without recovering IG32/IG37/IG46 "
    "expression anchors or eliminating the stack-frame drift while preserving "
    "the normalized opcode shape."
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context"
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON = (
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context-exhausted/"
    "no-floor-improvement"
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER = (
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context/"
    "no-target-or-expression-floor-improvement"
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-stack-loop-callsite-"
    "source-context"
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor loop-callsite source-context synthesis "
    "exhausted bounded digit object, animation callarg, translate-X/translate-Y "
    "owner, and add-child parent owner probes from the retained post-stack seed "
    "without recovering IG32/IG37/IG46 expression anchors or eliminating "
    "stack-frame drift under the structural guard. No further modeled "
    "source-actionable Draw family remains after this loop-callsite layer."
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY = (
    "draw-post-stack-loop-callsite-expression-anchor-source-ownership"
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL = (
    "Draw post-stack loop-callsite source-context exhaustion now needs "
    "expression-anchor source ownership for row/column FPR owners, "
    "col_product_owner split product, y_offset/row_offset row-delta source, "
    "and digit base assignment feeding HSD_JObjReqAnimAll."
)
DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION = (
    "draw-protected-expression-subhunk-reconcile"
)
DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON = (
    "draw-protected-expression-subhunk-reconcile-exhausted/"
    "protected-expression-not-retained"
)
DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-"
    "protected-expression-subhunk-reconcile"
)
DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL = (
    "Draw protected-expression subhunk reconciliation exhausted all scored "
    "recombines without retaining the protected expression anchors. No further "
    "modeled source-actionable Draw family remains after this reconcile layer."
)
DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
)
DRAW_HELPER_BOUNDARY_TERMINAL_KIND = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal"
)
DRAW_HELPER_BOUNDARY_TERMINAL_REASON = "all-inline-helper-candidates-rejected"
DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-exhausted/"
    "no-expression-progress"
)
DRAW_HELPER_BOUNDARY_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-helper-boundary-"
    "expression-lifetime"
)
DRAW_HELPER_BOUNDARY_FINAL_MODEL = (
    "Draw helper-boundary expression-lifetime synthesis exhausted bounded "
    "inline/block-helper source shapes after protected-expression reconcile "
    "without recovering the remaining IG32/IG37/IG46 expression anchors. No "
    "further modeled source-actionable Draw family remains in this lane; the "
    "remaining axis is non-source/codegen or allocator behavior."
)
_DRAW_HELPER_BOUNDARY_TERMINAL_REASONS = {
    DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
    DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
}
_DRAW_HELPER_BOUNDARY_DIRECT_PROOF_PATHS = (
    ("context", "current_ceiling"),
    ("context", "current_ceiling", "source_family_synthesis"),
    ("current_ceiling",),
    ("current_ceiling", "source_family_synthesis"),
    ("retained_frontiers_meta_ceiling", "terminal_proof"),
    ("meta_ceiling", "terminal_proof"),
)
_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIRECT_PROOF_PATHS = (
    ("context", "current_ceiling"),
    ("context", "current_ceiling", "source_family_synthesis"),
    ("current_ceiling",),
    ("current_ceiling", "source_family_synthesis"),
    ("retained_frontiers_meta_ceiling", "terminal_proof"),
    ("meta_ceiling", "terminal_proof"),
)


class PostSourceContextDiscoveryError(ValueError):
    """Raised when discovery input is malformed."""


class PostSourceContextFprCeilingNextDimensionDiscovery:
    """Discover the next handoff after Draw source-context exhaustion."""

    def discover(
        self,
        *,
        function: str,
        source_model: Mapping[str, Any] | None = None,
        retained_frontiers: Mapping[str, Any] | None = None,
        allocator_ceiling: Mapping[str, Any] | None = None,
        continuation: Mapping[str, Any] | None = None,
        source_file: str | None = None,
    ) -> dict[str, Any]:
        artifacts = [
            artifact
            for artifact in (
                source_model,
                retained_frontiers,
                allocator_ceiling,
                continuation,
            )
            if isinstance(artifact, Mapping)
        ]
        if function != DRAW_FUNCTION or not artifacts:
            return _not_applicable(function, "unsupported-function-or-empty-input")
        stage = _draw_post_source_context_stage(artifacts)
        if stage is None and not any(
            _contains_value(artifact, DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY)
            or _contains_value(artifact, DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY)
            for artifact in artifacts
        ):
            return _not_applicable(function, "source-context-final-family-not-found")
        if not _has_terminal_context(
            source_model=source_model,
            retained_frontiers=retained_frontiers,
            allocator_ceiling=allocator_ceiling,
        ):
            return _not_applicable(function, "source-context-ceiling-not-terminal")
        if stage is None:
            return _not_applicable(function, "source-context-dimension-not-exhausted")

        current_floor = _current_floor(artifacts)
        retained_evidence = _normalize_retained_evidence(
            artifacts,
            current_floor=current_floor,
        )
        retained_evidence = _stage_retained_evidence(stage, retained_evidence)
        if not retained_evidence:
            return _not_applicable(function, "retained-evidence-not-found")

        source_spans = _source_spans(artifacts, retained_evidence, source_file=source_file)
        ranked = sorted(retained_evidence, key=_rank_key)
        actionable = [
            row for row in ranked
            if row.get("target_floor_progress") is True
            or row.get("expression_floor_progress_real") is True
        ]
        base = {
            "kind": DISCOVERY_KIND,
            "family": DISCOVERY_FAMILY,
            "family_id": DISCOVERY_FAMILY,
            "function": function,
            "current_floor": current_floor,
            "trigger_family": stage["trigger_family"],
            "trigger_dimension": stage["trigger_dimension"],
            "source_spans": source_spans,
            "handoff": _handoff(function=function),
        }
        if actionable:
            probes = actionable
            next_frontier = _actionable_frontier(function, probes[0])
            return {
                **base,
                "status": "source-actionable",
                "next_frontier": next_frontier,
                "ranked_retained_c_probes": probes,
            }

        if stage["status"] == DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS:
            exhausted_dimensions = _stage_exhausted_dimensions(stage)
            payload = {
                **base,
                "status": DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS,
                "exhausted_source_dimension": stage["exhausted_source_dimension"],
                "exhausted_dimensions": exhausted_dimensions,
                "next_unsupported_source_family": stage[
                    "next_unsupported_source_family"
                ],
                "next_unsupported_source_model": stage[
                    "next_unsupported_source_model"
                ],
                "retained_evidence": ranked,
            }
            for key in (
                "terminal_reason",
                "terminal_blocker",
                "unsupported_source_expression_class",
                "unsupported_source_expression_model",
            ):
                value = stage.get(key)
                if value is not None:
                    payload[key] = value
            next_dimension = stage.get("next_unsupported_source_dimension")
            if isinstance(next_dimension, str) and next_dimension:
                payload["next_unsupported_source_dimension"] = next_dimension
            return payload

        return {
            **base,
            "status": "unsupported-source-dimension",
            "next_unsupported_source_dimension": stage[
                "next_unsupported_source_dimension"
            ],
            "next_unsupported_source_family": stage[
                "next_unsupported_source_family"
            ],
            "next_unsupported_source_model": stage["next_unsupported_source_model"],
            "retained_evidence": ranked,
        }


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PostSourceContextDiscoveryError(
            f"could not parse JSON artifact {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PostSourceContextDiscoveryError(f"artifact is not a JSON object: {path}")
    return payload


def _not_applicable(function: str, reason: str) -> dict[str, Any]:
    return {
        "kind": DISCOVERY_KIND,
        "status": "not-applicable",
        "function": function,
        "reason": reason,
    }


def _has_terminal_context(
    *,
    source_model: Mapping[str, Any] | None,
    retained_frontiers: Mapping[str, Any] | None,
    allocator_ceiling: Mapping[str, Any] | None,
) -> bool:
    if isinstance(source_model, Mapping) and source_model.get("status") == "terminal":
        return True
    if (
        isinstance(retained_frontiers, Mapping)
        and retained_frontiers.get("status") == "all-known-frontiers-exhausted"
    ):
        return True
    if (
        isinstance(allocator_ceiling, Mapping)
        and allocator_ceiling.get("status") == "practical-ceiling"
    ):
        return True
    return False


def _draw_post_source_context_stage(
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    helper_boundary_proofs = _helper_boundary_terminal_proofs(artifacts)
    if helper_boundary_proofs:
        exhausted_dimensions = _direct_proof_exhausted_dimensions(
            helper_boundary_proofs,
            stage_dimensions=[DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION],
        )
        return {
            "status": DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS,
            "trigger_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
            "trigger_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "exhausted_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "exhausted_dimensions": exhausted_dimensions,
            "terminal_reason": _helper_boundary_terminal_reason(
                helper_boundary_proofs
            ),
            "terminal_blocker": _helper_boundary_terminal_reason(
                helper_boundary_proofs
            ),
            "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
            "next_unsupported_source_model": DRAW_HELPER_BOUNDARY_FINAL_MODEL,
        }

    protected_reconcile_proofs = (
        _protected_expression_subhunk_reconcile_terminal_proofs(artifacts)
    )
    if protected_reconcile_proofs:
        exhausted_dimensions = _direct_proof_exhausted_dimensions(
            protected_reconcile_proofs,
            stage_dimensions=[
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
            ],
        )
        return {
            "status": DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS,
            "trigger_family": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
            ),
            "trigger_dimension": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
            ),
            "exhausted_source_dimension": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
            ),
            "exhausted_dimensions": exhausted_dimensions,
            "terminal_reason": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
            ),
            "terminal_blocker": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
            ),
            "next_unsupported_source_family": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
            ),
        }

    if _has_post_stack_loop_callsite_final_stage(artifacts):
        return {
            "status": DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS,
            "trigger_family": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
            ),
            "trigger_dimension": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            ),
            "exhausted_source_dimension": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            ),
            "exhausted_dimensions": [
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            ],
            "terminal_reason": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
            ),
            "terminal_blocker": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
            ),
            "next_unsupported_source_family": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
            ),
        }

    if _has_stack_clean_no_anchor_final_stage(artifacts):
        return {
            "status": DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS,
            "trigger_family": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY,
            "trigger_dimension": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "exhausted_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "exhausted_dimensions": [
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ],
            "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
            "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
            "next_unsupported_source_family": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
            ),
        }

    if _has_post_whole_function_stage(artifacts):
        exhausted_dimensions = _artifact_exhausted_dimensions(
            artifacts,
            stage_dimensions=[DRAW_POST_SOURCE_CONTEXT_DIMENSION],
        )
        next_dimension = _artifact_non_stale_next_dimension(
            artifacts,
            exhausted_dimensions,
        )
        return {
            "status": DRAW_POST_WHOLE_FUNCTION_TERMINAL_STATUS,
            "trigger_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
            "trigger_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            "exhausted_source_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            "exhausted_dimensions": sorted(exhausted_dimensions),
            "next_unsupported_source_dimension": next_dimension,
            "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
            "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
            "unsupported_source_expression_class": (
                _unsupported_source_expression_class(artifacts)
                or DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
            ),
            "unsupported_source_expression_model": (
                _artifact_first_string(artifacts, "unsupported_source_expression_model")
                or DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL
            ),
        }

    if any(
        _contains_value(artifact, DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY)
        for artifact in artifacts
    ) and any(
        _contains_value(artifact, DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION)
        for artifact in artifacts
    ):
        return {
            "status": "unsupported-source-dimension",
            "trigger_family": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY,
            "trigger_dimension": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
            "next_unsupported_source_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY,
            "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_MODEL,
        }
    return None


def _helper_boundary_terminal_proofs(
    artifacts: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    proofs: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for artifact in artifacts:
        for proof in _helper_boundary_direct_proofs(artifact):
            if id(proof) in seen:
                continue
            seen.add(id(proof))
            if _is_helper_boundary_terminal_proof(proof):
                proofs.append(proof)
    return proofs


def _helper_boundary_direct_proofs(
    artifact: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    for path in _DRAW_HELPER_BOUNDARY_DIRECT_PROOF_PATHS:
        proof = _nested_mapping(artifact, path)
        if proof is not None:
            yield proof
            synthesis = _nested_mapping(proof, ("source_family_synthesis",))
            if synthesis is not None:
                yield synthesis
    functions = artifact.get("functions")
    if not isinstance(functions, list):
        return
    for entry in functions:
        if not isinstance(entry, Mapping):
            continue
        proof = _nested_mapping(entry, ("meta_ceiling", "terminal_proof"))
        if proof is not None:
            yield proof
            synthesis = _nested_mapping(proof, ("source_family_synthesis",))
            if synthesis is not None:
                yield synthesis


def _is_helper_boundary_terminal_proof(proof: Mapping[str, Any]) -> bool:
    if proof.get("kind") == DRAW_HELPER_BOUNDARY_TERMINAL_KIND:
        return True
    if proof.get("next_unsupported_source_family") == DRAW_HELPER_BOUNDARY_FINAL_FAMILY:
        return True
    if proof.get("exhausted_source_dimension") == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION:
        return True
    for key in ("terminal_reason", "terminal_blocker"):
        if proof.get(key) in _DRAW_HELPER_BOUNDARY_TERMINAL_REASONS:
            return True
    for row in proof.get("exhausted_dimensions") or []:
        if _dimension_entry_id(row) == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION:
            return True
        if isinstance(row, Mapping) and row.get("exhaustion_reason") in (
            _DRAW_HELPER_BOUNDARY_TERMINAL_REASONS
        ):
            return True
    return False


def _helper_boundary_terminal_reason(
    proofs: Sequence[Mapping[str, Any]],
) -> str:
    for proof in proofs:
        for key in ("terminal_reason", "terminal_blocker"):
            value = proof.get(key)
            if value in _DRAW_HELPER_BOUNDARY_TERMINAL_REASONS:
                return str(value)
        for row in proof.get("exhausted_dimensions") or []:
            if isinstance(row, Mapping) and row.get("exhaustion_reason") in (
                _DRAW_HELPER_BOUNDARY_TERMINAL_REASONS
            ):
                return str(row["exhaustion_reason"])
    return DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON


def _protected_expression_subhunk_reconcile_terminal_proofs(
    artifacts: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    proofs: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for artifact in artifacts:
        for proof in _protected_expression_subhunk_reconcile_direct_proofs(artifact):
            if id(proof) in seen:
                continue
            seen.add(id(proof))
            if _is_protected_expression_subhunk_reconcile_terminal_proof(proof):
                proofs.append(proof)
    return proofs


def _protected_expression_subhunk_reconcile_direct_proofs(
    artifact: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    for path in _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIRECT_PROOF_PATHS:
        proof = _nested_mapping(artifact, path)
        if proof is not None:
            yield proof
            synthesis = _nested_mapping(proof, ("source_family_synthesis",))
            if synthesis is not None:
                yield synthesis
    functions = artifact.get("functions")
    if not isinstance(functions, list):
        return
    for entry in functions:
        if not isinstance(entry, Mapping):
            continue
        proof = _nested_mapping(entry, ("meta_ceiling", "terminal_proof"))
        if proof is not None:
            yield proof
            synthesis = _nested_mapping(proof, ("source_family_synthesis",))
            if synthesis is not None:
                yield synthesis


def _is_protected_expression_subhunk_reconcile_terminal_proof(
    proof: Mapping[str, Any],
) -> bool:
    if (
        proof.get("next_unsupported_source_family")
        == DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    ):
        return True
    if (
        proof.get("terminal_reason")
        == DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    ):
        return True
    if (
        proof.get("terminal_blocker")
        == DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    ):
        return True
    if (
        proof.get("exhausted_source_dimension")
        == DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
    ):
        return True
    for row in proof.get("exhausted_dimensions") or []:
        if (
            _dimension_entry_id(row)
            == DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
        ):
            return True
        if isinstance(row, Mapping) and row.get("exhaustion_reason") == (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
        ):
            return True
    return False


def _direct_proof_exhausted_dimensions(
    proofs: Sequence[Mapping[str, Any]],
    *,
    stage_dimensions: Sequence[str],
) -> list[str]:
    exhausted: list[str] = []

    def add(dimension: str | None) -> None:
        if dimension and dimension not in exhausted:
            exhausted.append(dimension)

    for dimension in stage_dimensions:
        add(dimension)
    for proof in proofs:
        add(_str_value(proof.get("exhausted_source_dimension")))
        for row in proof.get("exhausted_dimensions") or []:
            add(_dimension_entry_id(row))
        if proof.get("status") in {"terminal", "scored-terminal", "exhausted"}:
            add(_str_value(proof.get("dimension_id")))
    return exhausted


def _has_post_stack_loop_callsite_final_stage(
    artifacts: Sequence[Mapping[str, Any]],
) -> bool:
    if any(
        _contains_value(
            artifact,
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY,
        )
        or _contains_value(
            artifact,
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL,
        )
        or _contains_value(
            artifact,
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY,
        )
        or _contains_value(
            artifact,
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL,
        )
        or _contains_value(
            artifact,
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON,
        )
        or _contains_value(
            artifact,
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER,
        )
        for artifact in artifacts
    ):
        return True
    if _artifact_contains_exhausted_dimension(
        artifacts,
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
    ):
        return True
    return _terminal_artifact_has_scored_row(
        artifacts,
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
    )


def _has_stack_clean_no_anchor_final_stage(
    artifacts: Sequence[Mapping[str, Any]],
) -> bool:
    if any(
        _contains_value(artifact, DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY)
        or _contains_value(artifact, DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL)
        or _contains_value(
            artifact,
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        )
        or _contains_value(
            artifact,
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
        )
        for artifact in artifacts
    ):
        return True
    return _artifact_contains_stack_clean_final_exhausted_dimension(artifacts)


def _artifact_contains_stack_clean_final_exhausted_dimension(
    artifacts: Sequence[Mapping[str, Any]],
) -> bool:
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            for row in mapping.get("exhausted_dimensions") or []:
                if not isinstance(row, Mapping):
                    continue
                if row.get("dimension_id") != (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
                ):
                    continue
                if row.get("status") in {
                    "terminal",
                    "scored-terminal",
                    "exhausted",
                }:
                    return True
                if row.get("exhaustion_reason") == (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
                ):
                    return True
            if (
                mapping.get("dimension_id")
                == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
                and mapping.get("status")
                in {"terminal", "scored-terminal", "exhausted"}
            ):
                return True
    return False


def _has_post_whole_function_stage(artifacts: Sequence[Mapping[str, Any]]) -> bool:
    has_final_signal = any(
        _contains_value(artifact, DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY)
        or _contains_value(artifact, DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS)
        or _contains_value(artifact, DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL)
        for artifact in artifacts
    )
    for mapping in _walk_mappings(artifacts):
        if mapping.get("terminal_reason") == DRAW_POST_WHOLE_FUNCTION_TERMINAL_REASON:
            has_final_signal = True
            break
    if not has_final_signal:
        return False
    if _artifact_contains_exhausted_dimension(
        artifacts,
        DRAW_POST_SOURCE_CONTEXT_DIMENSION,
    ):
        return True
    if _terminal_artifact_has_scored_row(artifacts, DRAW_POST_SOURCE_CONTEXT_DIMENSION):
        return True
    return False


def _artifact_first_string(
    artifacts: Sequence[Mapping[str, Any]],
    key: str,
    *,
    exclude: Sequence[str] = (),
) -> str | None:
    excluded = set(exclude)
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            value = mapping.get(key)
            if isinstance(value, str) and value and value not in excluded:
                return value
    return None


def _artifact_contains_exhausted_dimension(
    artifacts: Sequence[Mapping[str, Any]],
    dimension_id: str,
) -> bool:
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            for row in mapping.get("exhausted_dimensions") or []:
                if _dimension_entry_id(row) == dimension_id:
                    return True
            if (
                mapping.get("dimension_id") == dimension_id
                and mapping.get("status") in {"terminal", "scored-terminal", "exhausted"}
            ):
                return True
    return False


def _artifact_non_stale_next_dimension(
    artifacts: Sequence[Mapping[str, Any]],
    exhausted_dimensions: Collection[str],
) -> str | None:
    exhausted = set(exhausted_dimensions)
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            value = mapping.get("next_unsupported_source_dimension")
            if isinstance(value, str) and value and value not in exhausted:
                return value
    return None


def _artifact_exhausted_dimensions(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    stage_dimensions: Sequence[str],
) -> set[str]:
    exhausted = {item for item in stage_dimensions if item}
    if _has_stack_clean_no_anchor_final_stage(artifacts):
        exhausted.add(DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION)
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            dimension = _str_value(mapping.get("exhausted_source_dimension"))
            if dimension:
                exhausted.add(dimension)
            for row in mapping.get("exhausted_dimensions") or []:
                dimension = _dimension_entry_id(row)
                if dimension:
                    exhausted.add(dimension)
            dimension = _str_value(mapping.get("dimension_id"))
            if (
                dimension
                and mapping.get("status") in {"terminal", "scored-terminal", "exhausted"}
            ):
                exhausted.add(dimension)
    return exhausted


def _stage_exhausted_dimensions(stage: Mapping[str, Any]) -> list[str]:
    exhausted: list[str] = []
    source_dimension = _str_value(stage.get("exhausted_source_dimension"))
    if source_dimension:
        exhausted.append(source_dimension)
    for row in stage.get("exhausted_dimensions") or []:
        dimension = _dimension_entry_id(row)
        if dimension and dimension not in exhausted:
            exhausted.append(dimension)
    return exhausted


def _unsupported_source_expression_class(
    artifacts: Sequence[Mapping[str, Any]],
) -> str | None:
    return _artifact_first_string(artifacts, "unsupported_source_expression_class")


def _terminal_artifact_has_scored_row(
    artifacts: Sequence[Mapping[str, Any]],
    dimension_id: str,
) -> bool:
    for artifact in artifacts:
        if artifact.get("status") != "terminal":
            continue
        for mapping in _walk_mappings(artifact):
            for key in ("candidate_scores", "retained_scored_probes"):
                for row in mapping.get(key) or []:
                    if isinstance(row, Mapping) and row.get("dimension_id") == dimension_id:
                        return True
    return False


def _dimension_entry_id(row: Any) -> str | None:
    if isinstance(row, str):
        return row if row else None
    if isinstance(row, Mapping):
        value = row.get("dimension_id") or row.get("id")
        return value if isinstance(value, str) and value else None
    return None


def _stage_retained_evidence(
    stage: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    dimension = stage.get("trigger_dimension")
    if not isinstance(dimension, str) or not dimension:
        return [dict(row) for row in rows]
    matching = [dict(row) for row in rows if row.get("dimension_id") == dimension]
    return matching or [dict(row) for row in rows]


def _current_floor(artifacts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            floor = mapping.get("current_floor") or mapping.get("floor")
            if isinstance(floor, Mapping):
                target = _int_value(floor.get("target") or floor.get("target_matched"))
                expression = _int_value(
                    floor.get("expression") or floor.get("expression_matched")
                )
                if target is not None or expression is not None:
                    return {
                        "target": target if target is not None else 1,
                        "expression": expression if expression is not None else 1,
                    }
            blockers = mapping.get("terminal_blockers")
            if isinstance(blockers, list):
                for blocker in blockers:
                    if not isinstance(blocker, Mapping):
                        continue
                    floor = blocker.get("floor")
                    if not isinstance(floor, Mapping):
                        continue
                    target = _int_value(floor.get("target"))
                    expression = _int_value(floor.get("expression"))
                    if target is not None or expression is not None:
                        return {
                            "target": target if target is not None else 1,
                            "expression": expression if expression is not None else 1,
                        }
    return dict(DRAW_POST_SOURCE_CONTEXT_DEFAULT_FLOOR)


def _normalize_retained_evidence(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    current_floor: Mapping[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        rows.extend(_mapping_list(artifact, "candidate_scores"))
        rows.extend(_mapping_list(artifact, "retained_scored_probes"))
        rows.extend(_mapping_list(artifact, "ranked_retained_candidates"))
        rows.extend(_mapping_list(artifact, "retained_candidates"))
        for path in (
            ("source_model_proof",),
            ("context", "current_ceiling"),
            ("context", "current_ceiling", "source_family_synthesis"),
            ("meta_ceiling", "terminal_proof"),
            ("current_ceiling",),
            ("current_ceiling", "source_family_synthesis"),
            ("retained_frontiers_meta_ceiling", "terminal_proof"),
        ):
            proof = _nested_mapping(artifact, path)
            if proof is not None:
                rows.extend(_mapping_list(proof, "candidate_scores"))
                rows.extend(_mapping_list(proof, "retained_scored_probes"))
                rows.extend(_mapping_list(proof, "ranked_retained_candidates"))
                rows.extend(_mapping_list(proof, "retained_candidates"))
        best = artifact.get("best_score_summary")
        if isinstance(best, Mapping):
            rows.extend(_mapping_list(best, "ranked_retained_candidates"))
            rows.extend(_mapping_list(best, "retained_candidates"))

    normalized: list[dict[str, Any]] = []
    for row in rows:
        out = _normalize_row(row, current_floor=current_floor)
        if out is not None:
            normalized.append(out)
    return _dedupe_rows(normalized)


def _normalize_row(
    row: Mapping[str, Any],
    *,
    current_floor: Mapping[str, int],
) -> dict[str, Any] | None:
    candidate_id = _str_value(row.get("candidate_id") or row.get("probe_id"))
    dimension_id = _str_value(row.get("dimension_id"))
    if not candidate_id and not dimension_id and not row.get("pcdump_path"):
        return None
    target_score = row.get("target_score") if isinstance(row.get("target_score"), Mapping) else {}
    expression_score = (
        row.get("expression_score")
        if isinstance(row.get("expression_score"), Mapping)
        else {}
    )
    target_matched = _first_int(row, target_score, "target_matched", "matched")
    expression_matched = _first_int(
        row,
        expression_score,
        "expression_matched",
        "matched",
    )
    target_total = _first_int(row, target_score, "target_targeted", "targeted")
    expression_total = _first_int(
        row,
        expression_score,
        "expression_targeted",
        "targeted",
    )
    real_expression = _real_expression_matched(row, expression_score, expression_matched)
    floor = {
        "target": _int_value(current_floor.get("target")) or 1,
        "expression": _int_value(current_floor.get("expression")) or 1,
    }
    target_progress = (target_matched or 0) > floor["target"]
    expression_progress = real_expression > floor["expression"]
    structural_guard = row.get("structural_guard")
    normalized_diff = _first_float(
        row,
        structural_guard if isinstance(structural_guard, Mapping) else {},
        "normalized_diff_lines",
    )
    opcode_similarity = _first_float(
        row,
        structural_guard if isinstance(structural_guard, Mapping) else {},
        "opcode_similarity",
    )
    frame_delta = _first_float(
        row,
        structural_guard if isinstance(structural_guard, Mapping) else {},
        "frame_delta",
    )
    out: dict[str, Any] = {
        "candidate_id": candidate_id,
        "dimension_id": dimension_id,
        "source_retained": row.get("source_retained"),
        "source_hunks": _list_value(row.get("source_hunks")),
        "source_components": _list_value(row.get("source_components")),
        "pcdump_path": row.get("pcdump_path"),
        "target_score": row.get("target_score"),
        "expression_score": row.get("expression_score"),
        "target_matched": target_matched,
        "target_total": target_total,
        "expression_matched": expression_matched,
        "expression_total": expression_total,
        "real_expression_matched": real_expression,
        "target_floor_progress": target_progress,
        "expression_floor_progress_real": expression_progress,
        "expression_renumbering_only": (
            expression_matched is not None
            and expression_matched > real_expression
            and not expression_progress
        ),
        "floor_progress": bool(target_progress or expression_progress),
        "wrong_registers": _list_value(row.get("wrong_registers")),
        "expression_wrong_registers": _list_value(
            row.get("expression_wrong_registers")
        ),
        "structural_guard": row.get("structural_guard"),
        "normalized_diff_lines": normalized_diff,
        "opcode_similarity": opcode_similarity,
        "frame_delta": frame_delta,
        "false_positive_virtual_id_hit_count": max(
            _false_positive_count(expression_score),
            _false_positive_count(row),
        ),
    }
    for key in (
        "renumbered",
        "renumbered_fsubs",
        "false_positive_virtual_id_hits",
        "classification",
        "structural_guard_accepted",
        "blockers",
    ):
        value = row.get(key)
        if value is None and isinstance(expression_score, Mapping):
            value = expression_score.get(key)
        if value is not None:
            out[key] = value
    return {key: value for key, value in out.items() if value is not None}


def _real_expression_matched(
    row: Mapping[str, Any],
    expression_score: Mapping[str, Any],
    expression_matched: int | None,
) -> int:
    matched = expression_matched
    if matched is None:
        matched = _int_value(expression_score.get("matched")) or 0
    false_positive = max(
        _false_positive_count(expression_score),
        _false_positive_count(row),
    )
    renumbered_only = _renumbered_only_count(expression_score)
    explicit = _int_value(row.get("real_expression_matched"))
    if explicit is not None:
        return max(0, explicit)
    return max(0, matched - false_positive - renumbered_only)


def _false_positive_count(expression_score: Mapping[str, Any]) -> int:
    count = _int_value(expression_score.get("false_positive_virtual_id_hit_count"))
    if count is not None:
        return max(0, count)
    hits = expression_score.get("false_positive_virtual_id_hits")
    return len(hits) if isinstance(hits, list) else 0


def _renumbered_only_count(expression_score: Mapping[str, Any]) -> int:
    count = _int_value(expression_score.get("renumbered_fsubs"))
    if count is None:
        count = _int_value(expression_score.get("renumbered"))
    if count is None:
        count = 0
    virtuals = expression_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return max(0, count)
    renumbered_matches = 0
    for virtual in virtuals.values():
        if not isinstance(virtual, Mapping):
            continue
        if virtual.get("matched") is True and virtual.get("renumbered") is True:
            renumbered_matches += 1
    return max(renumbered_matches, count)


def _source_spans(
    artifacts: Sequence[Mapping[str, Any]],
    retained_evidence: Sequence[Mapping[str, Any]],
    *,
    source_file: str | None,
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for artifact in artifacts:
        for mapping in _walk_mappings(artifact):
            for key in ("next_unsupported_source_spans", "source_spans"):
                for row in _mapping_list(mapping, key):
                    spans.append(dict(row))
    for evidence in retained_evidence:
        for hunk in evidence.get("source_hunks") or []:
            if not isinstance(hunk, Mapping):
                continue
            span: dict[str, Any] = {
                "confidence": "retained-evidence-source-hunk",
                "candidate_id": evidence.get("candidate_id"),
                "dimension_id": evidence.get("dimension_id"),
            }
            if source_file:
                span["source_file"] = source_file
            line = _int_value(hunk.get("old_start") or hunk.get("base_start"))
            if line is not None:
                span["source_line"] = line
            hunk_id = _str_value(hunk.get("hunk_id"))
            if hunk_id:
                span["hunk_id"] = hunk_id
            spans.append({key: value for key, value in span.items() if value is not None})
    if source_file:
        spans.append({"source_file": source_file, "confidence": "requested-source-file"})
    return _dedupe_dicts(spans)


def _actionable_frontier(function: str, probe: Mapping[str, Any]) -> dict[str, Any]:
    continuation = {
        "route": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "candidate_id": probe.get("candidate_id"),
        "source_hunks": probe.get("source_hunks") or [],
        "source_retained": probe.get("source_retained"),
        "pcdump_path": probe.get("pcdump_path"),
        "target_score": probe.get("target_score"),
        "expression_score": probe.get("expression_score"),
    }
    return {
        "function": function,
        "family_id": DISCOVERY_FAMILY,
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "kind": DISCOVERY_KIND,
        "status": "source-actionable",
        "actionable": True,
        "continuation": {
            key: value for key, value in continuation.items()
            if value is not None
        },
        "source_hunks": probe.get("source_hunks") or [],
        "source_retained": probe.get("source_retained"),
        "pcdump_path": probe.get("pcdump_path"),
        "target_score": probe.get("target_score"),
        "expression_score": probe.get("expression_score"),
    }


def _handoff(*, function: str) -> dict[str, Any]:
    retained_cmd = [
        "melee-agent",
        "debug",
        "search",
        "retained-frontiers",
        "--function",
        function,
        "--artifact",
        "<post-source-context-next-dimension-json>",
        "--json",
    ]
    allocator_cmd = [
        "melee-agent",
        "debug",
        "solve",
        "allocator-ceiling",
        "--function",
        function,
        "--evidence",
        "<retained-frontiers-json-with-discovery>",
        "--json",
    ]
    return {
        "retained_frontiers": {
            "command": shlex.join(retained_cmd),
            "requires_explicit_artifact": True,
        },
        "allocator": {
            "command": shlex.join(allocator_cmd),
            "requires_explicit_retained_frontiers_artifact": True,
        },
    }


def _rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    guard = row.get("structural_guard")
    guard_accepted = False
    if isinstance(guard, Mapping):
        guard_accepted = guard.get("accepted") is True or guard.get("shape_preserved") is True
    if row.get("structural_guard_accepted") is True:
        guard_accepted = True
    normalized_diff = row.get("normalized_diff_lines")
    opcode_similarity = row.get("opcode_similarity")
    frame_delta = row.get("frame_delta")
    return (
        0 if row.get("floor_progress") else 1,
        0 if guard_accepted else 1,
        -(_int_value(row.get("target_matched")) or 0),
        -(_int_value(row.get("real_expression_matched")) or 0),
        float(normalized_diff) if isinstance(normalized_diff, (int, float)) else math.inf,
        -float(opcode_similarity) if isinstance(opcode_similarity, (int, float)) else math.inf,
        abs(float(frame_delta)) if isinstance(frame_delta, (int, float)) else math.inf,
        0 if row.get("source_hunks") and row.get("pcdump_path") else 1,
        str(row.get("candidate_id") or ""),
    )


def _dedupe_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = _row_identity(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _row_identity(row: Mapping[str, Any]) -> str:
    candidate_id = _str_value(row.get("candidate_id"))
    dimension_id = _str_value(row.get("dimension_id"))
    pcdump_path = _str_value(row.get("pcdump_path"))
    if candidate_id or dimension_id or pcdump_path:
        return "|".join([candidate_id or "", dimension_id or "", pcdump_path or ""])
    hunks = row.get("source_hunks")
    if isinstance(hunks, list) and hunks:
        return json.dumps(hunks[0], sort_keys=True, default=str)
    return json.dumps(row, sort_keys=True, default=str)


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _contains_value(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return value == needle
    if isinstance(value, Mapping):
        return any(_contains_value(child, needle) for child in value.values())
    if isinstance(value, list):
        return any(_contains_value(child, needle) for child in value)
    return False


def _nested_mapping(
    mapping: Mapping[str, Any],
    path: Sequence[str],
) -> Mapping[str, Any] | None:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def _mapping_list(mapping: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = mapping.get(key)
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_int(
    row: Mapping[str, Any],
    score: Mapping[str, Any],
    row_key: str,
    score_key: str,
) -> int | None:
    value = _int_value(row.get(row_key))
    if value is not None:
        return value
    return _int_value(score.get(score_key))


def _first_float(
    row: Mapping[str, Any],
    score: Mapping[str, Any],
    key: str,
) -> float | None:
    value = _float_value(row.get(key))
    if value is not None:
        return value
    return _float_value(score.get(key))


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _dedupe_dicts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out
