import json
import os
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.mwcc_debug.post_meta_source_family_synthesis import (
    build_source_family_continuation_payload,
)
from src.mwcc_debug.retained_frontier_triage import (
    RetainedFrontierTriageError,
    render_retained_frontier_text,
    retained_frontier_meta_ceiling_from_payloads,
    retained_frontier_meta_rank,
    synthesize_retained_frontier_meta_ceiling,
    triage_retained_frontiers,
)
from src.search.cli import search_app

DRAW_COUPLED_UNSUPPORTED_CLASS = "draw-coupled-post-meta-fpr-expression-lifetime"
DRAW_COUPLED_UNSUPPORTED_MODEL = (
    "Draw coupled post-meta FPR expression lifetime/materialization across "
    "col_offset product, row_offset fsubs, and digit-animation fsubs/callarg temp."
)
DRAW_COUPLED_LIFETIME_DIMENSION = "draw-coupled-fpr-expression-lifetime"
DRAW_ALTERNATE_DIMENSION = "draw-alternate-fpr-expression-structure"
DRAW_ALTERNATE_TERMINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-alternate-fpr-expression-structure"
)
DRAW_ALTERNATE_TERMINAL_MODEL = (
    "Draw alternate FPR expression-structure synthesis exhausted bounded "
    "coupled col_offset/row_offset/digit-callarg expression graph variants; "
    "no modeled source-actionable Draw family remains."
)
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION = (
    "draw-loop-body-callsite-and-object-base-lifetime-source-context"
)
DRAW_POST_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-source-context-whole-function-fpr-source-model"
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
DRAW_POST_ALL_KNOWN_DIMENSION = (
    "draw-post-all-known-frontiers-source-context-hypothesis"
)
DRAW_POST_ALL_KNOWN_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-all-known-frontiers-"
    "source-context-hypothesis"
)
DRAW_POST_ALL_KNOWN_FINAL_MODEL = (
    "Draw post-all-known source-context hypothesis after whole-function FPR "
    "ceiling exhausted bounded recombinations and wider source-context owner "
    "shapes without improving the retained target/real-expression floor."
)
DRAW_PRODUCT_TRANSLATE_DIMENSION = (
    "draw-post-all-known-loop-product-translate-expression-graph"
)
DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-all-known-loop-"
    "product-translate-expression-graph"
)
DRAW_PRODUCT_TRANSLATE_FINAL_MODEL = (
    "Draw post-all-known loop product/translate expression-graph synthesis "
    "exhausted bounded loop-index translate, col/row product owner, row-delta "
    "product, and common translate-X call-shape variants without improving the "
    "retained target/real-expression floor. No further modeled source-actionable "
    "Draw family remains after this product/translate expression-graph layer."
)
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
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis"
)
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL = (
    "Draw post-stack-clean/no-anchor FPR source-shape synthesis from the "
    "stack-clean final proof, testing declaration packing, row/column owner "
    "reuse, digit base lifetime, and frame-neutral owner coalescing against "
    "IG32/IG37/IG46 plus the +8 frame drift."
)
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis-exhausted/"
    "no-floor-improvement"
)
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis/"
    "no-source-actionable-anchor-or-frame-recovery"
)
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-"
    "fpr-source-shape-hypothesis"
)
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor FPR source-shape synthesis exhausted "
    "bounded declaration-packing, row/column owner reuse, digit base lifetime, "
    "coupled row/column, and frame-neutral coalescing probes without recovering "
    "IG32/IG37/IG46 expression anchors or eliminating the stack-frame drift "
    "under the structural guard."
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
    "stack-frame drift under the structural guard."
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY = (
    "draw-post-stack-loop-callsite-expression-anchor-source-ownership"
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION = (
    DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL = (
    "Draw post-stack loop-callsite source-context exhaustion now needs "
    "expression-anchor source ownership for row/column FPR owners, "
    "col_product_owner split product, y_offset/row_offset row-delta source, "
    "and digit base assignment feeding HSD_JObjReqAnimAll."
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON = (
    "draw-post-stack-loop-callsite-expression-anchor-source-ownership-exhausted/"
    "no-owner-progress"
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_BLOCKER = (
    "draw-post-stack-loop-callsite-expression-anchor-source-ownership/"
    "no-target-or-expression-floor-improvement"
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-split"
)
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_MODEL = (
    "Draw expression-anchor source-ownership synthesis exhausted bounded "
    "row-offset owner split, col-product owner split, and digit-base owner "
    "probes after the retained loop-callsite seed."
)
DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION = (
    "draw-post-row-offset-owner-expression-lifetime"
)
DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON = (
    "draw-post-row-offset-owner-expression-lifetime-exhausted/no-lifetime-progress"
)
DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER = (
    "draw-post-row-offset-owner-expression-lifetime/"
    "no-target-or-expression-floor-improvement"
)
DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-expression-lifetime"
)
DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL = (
    "Draw post-row-offset-owner expression lifetime synthesis exhausted "
    "bounded row_offset_adj translate-Y, column product, digit callsite, and "
    "coupled lifetime probes from the retained owner-split floor."
)
DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
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
DRAW_HELPER_BOUNDARY_REJECTION_REASON = (
    "span writes locals; void-helper extraction would need output params"
)
SORT_LEGACY_UNSUPPORTED_MODEL = (
    "This #981-era artifact has no source-family discovery or plateau data; "
    "only the retained Sort local source-model candidates were scored."
)
SORT_ONE_HIT_UNSUPPORTED_MODEL = (
    "Post-meta Sort one-hit continuation exhausted bounded structural repair "
    "and pairwise recombination of IG34/IG44 source-family hits; the next "
    "unsupported model is a broader natural C sort rewrite outside these "
    "retained source families."
)
SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL = (
    "Sort protected-loss repair exhausted bounded manual subhunk splits. "
    "The next source lever is a lower-drift-preserving init-lifetime variant "
    "that keeps the full IG44 predicate/local-copy block while changing only "
    "the IG34 name-byte/total materialization."
)
SORT_POST_LOWER_DRIFT_MODEL = (
    "Sort protected-loss init-lifetime scoring exhausted the bounded lower-drift "
    "source family without jointly preserving IG34/IG44. The next unsupported "
    "source model is the full Sort selection/swap source structure outside the "
    "current protected-loss and init-lifetime families."
)
SORT_WHOLE_FUNCTION_DIMENSION = "sort-whole-function-control-data-flow-rewrite"
SORT_HELPER_DATA_LAYOUT_FAMILY = (
    "sort-helper-extraction-data-layout-or-cross-function-rewrite"
)
SORT_CROSS_TU_DIMENSION = (
    "sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context"
)
SORT_POST_CROSS_TU_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-cross-tu-linkage"
)
SORT_CROSS_TU_MODEL = (
    "Sort cross-TU symbol/linkage and compiler data-section ownership "
    "source-context synthesis exhausted bounded cross-TU source-context rows "
    "and complementary one-hit recombine evidence without jointly recovering "
    "IG34/IG44. No further modeled source-actionable Sort family remains after "
    "the cross-TU linkage layer."
)
SORT_CROSS_TU_NO_MODELED_BLOCKER = (
    "no-modeled-source-actionable-family-after-cross-tu-linkage"
)
SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION = (
    "sort-post-cross-tu-selection-swap-source-hypothesis"
)
SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-selection-swap-source-hypothesis"
)
SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_MODEL = (
    "Sort post-cross-TU selection/swap source hypothesis layer exhausted "
    "bounded combined source-region probes after the cross-TU layer without "
    "jointly preserving IG34/IG44. No further modeled source-actionable Sort "
    "family remains after this post-cross-TU selection/swap source hypothesis "
    "layer."
)
SORT_POST_CROSS_TU_BROADER_NATURAL_DIMENSION = (
    "sort-post-cross-tu-broader-natural-c-rewrite"
)
SORT_POST_CROSS_TU_BROADER_NATURAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite"
)
SORT_POST_CROSS_TU_BROADER_NATURAL_MODEL = (
    "Sort post-cross-TU broader natural C rewrite synthesis exhausted "
    "bounded full-unit sort-region rewrites seeded from the retained IG44 "
    "one-hit post-cross-TU selection/swap probe without jointly preserving "
    "IG34/IG44 under the structural guard. No further modeled "
    "source-actionable Sort family remains after this broader natural C "
    "rewrite layer."
)
SORT_POST_BROADER_INLINE_BOUNDARY_DIMENSION = (
    "sort-post-broader-natural-inline-boundary-source-hypothesis"
)
SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis"
)
SORT_POST_BROADER_INLINE_BOUNDARY_MODEL = (
    "Sort post-broader-natural inline-boundary source-hypothesis synthesis "
    "exhausted bounded comparison decision/helper-boundary probes seeded from "
    "the lower-drift broader-natural row without jointly preserving IG34/IG44 "
    "under the structural guard. No further modeled source-actionable Sort "
    "family remains after this post-broader-natural inline-boundary layer."
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION = (
    "sort-post-inline-boundary-selection-emission-source-shape"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-inline-boundary-"
    "selection-emission-source-shape"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_MODEL = (
    "Sort post-inline-boundary selection/emission source-shape synthesis "
    "exhausted bounded selected-name carry, selected total/text lifetime, and "
    "selected-name emission-owner probes seeded from the retained "
    "post-broader inline-boundary one-hit row without jointly preserving "
    "IG34/IG44 under the structural guard."
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _common_subexpr_residual_hit_payload(
    function: str = "mnDiagram_SortNamesByKOs",
) -> dict:
    source_retained = "build/probes/retained_gpr_common_subexpr_coalesce_source@0.c"
    pcdump_path = "/tmp/work/build/probes/retained_gpr_common_subexpr_coalesce_source@0.pcdump.txt"
    target_score = {
        "total": 65.0,
        "matched": 1,
        "targeted": 2,
        "virtuals": {
            "34": {"expected": 27, "actual": 29, "matched": False},
            "44": {"expected": 25, "actual": 25, "matched": True},
        },
    }
    source_hunks = [
        {
            "line_start": 924,
            "line_end": 924,
            "replacement_text": "    u8* common_source_r39_probe;",
            "kind": "common-subexpr-source-owner-shared-base",
        },
        {
            "line_start": 926,
            "line_end": 926,
            "span_text": "    dst_iter = dst;",
            "replacement_text": "    dst_iter = common_source_r39_probe;",
            "kind": "common-subexpr-source-owner-rewrite",
            "var": "dst_iter",
        },
    ]
    return {
        "plan": {"function": function},
        "retained_gpr_common_subexpr_coalesce_source_summary": {
            "status": "residual-hit",
            "kind": "retained-gpr-common-subexpr-coalesce-source",
            "protected_targets": {"34": 27, "44": 25},
            "attempted_targets": {},
            "materialized_probe_count": 2,
            "evaluated_probe_count": 2,
            "exact_count": 0,
            "residual_hit_count": 1,
            "residual_force_phys": {"34": 27, "44": 25},
            "preserved_force_phys": {"44": 25},
            "stop_condition": "common-subexpr-coalesce-source-residual-hit",
            "best_retained_candidates": [
                {
                    "probe_id": "retained_gpr_common_subexpr_coalesce_source@0",
                    "source_retained": source_retained,
                    "pcdump_path": pcdump_path,
                    "target_score": target_score,
                    "source_hunks": source_hunks,
                    "coalesce_pair": {"from": 35, "to": 42},
                    "common_source_virtual": 39,
                    "source_owner_strategy": "common-source-shared-base-temp",
                    "source_owner_candidates": [
                        {
                            "var": "dst_iter",
                            "line": 926,
                            "type": "u8*",
                            "rhs": "dst",
                            "kind": "assignment",
                        }
                    ],
                    "payload": {
                        "family_id": "retained-gpr-common-subexpr-coalesce-source",
                        "target_score": target_score,
                    },
                }
            ],
        },
    }


def _common_subexpr_residual_simplify_exhaustion(
    function: str = "mnDiagram_SortNamesByKOs",
) -> dict:
    source_file = "/tmp/work/build/probes/retained_gpr_common_subexpr_coalesce_source@0.c"
    return {
        "function": function,
        "terminal_blocker": "no-retained-candidate-improved-residual-force-phys",
        "retained_mode": True,
        "source_file": source_file,
        "pcdump": source_file.replace(".c", ".pcdump.txt"),
        "protected_force_phys": {"44": 25},
        "residual_force_phys": {"34": 27},
        "summary": {
            "compiled": 40,
            "skipped": 0,
            "compile_failures": 3,
            "gate_rejected": 27,
            "progress_hits": 0,
        },
        "ranked_probes": [
            {
                "rank": 1,
                "target_score": {
                    "virtuals": {
                        "34": {"expected": 27, "actual": 29, "matched": False},
                        "44": {"expected": 25, "actual": 25, "matched": True},
                    }
                },
            }
        ],
    }


def _sort_force() -> dict[str, int]:
    return {"34": 27, "44": 25}


def _sort_issue1069_target_score(*, hit_virtual: str) -> dict:
    return {
        "matched": 1,
        "targeted": 2,
        "virtual_distance": 1,
        "virtuals": {
            "34": {
                "expected": 27,
                "actual": 27 if hit_virtual == "34" else 22,
                "matched": hit_virtual == "34",
            },
            "44": {
                "expected": 25,
                "actual": 25 if hit_virtual == "44" else 22,
                "matched": hit_virtual == "44",
            },
        },
    }


def _sort_issue1069_score_rows() -> list[dict]:
    source_dir = "build/diagnostics/mndiagram_1067_rerun/post_inline_local_write"
    return [
        {
            "candidate_id": (
                "post-meta-source-family-sort-init-indexed-write-name-total-locals"
            ),
            "dimension_id": "sort-init-indexed-write",
            "target_matched": 1,
            "target_targeted": 2,
            "target_virtual_distance": 1,
            "target_score": _sort_issue1069_target_score(hit_virtual="34"),
            "normalized_diff_lines": 5,
            "structural_guard": {"accepted": False, "normalized_diff_lines": 5},
            "source_retained": (
                f"{source_dir}/"
                "post-meta-source-family-sort-init-indexed-write-name-total-locals.c"
            ),
            "pcdump_path": (
                f"{source_dir}/"
                "post-meta-source-family-sort-init-indexed-write-name-total-locals.pcdump.txt"
            ),
        },
        {
            "candidate_id": (
                "post-meta-source-family-sort-call-return-copy-local-max-text-copy"
            ),
            "dimension_id": "sort-call-return-copy-local",
            "target_matched": 1,
            "target_targeted": 2,
            "target_virtual_distance": 1,
            "target_score": _sort_issue1069_target_score(hit_virtual="44"),
            "normalized_diff_lines": 9,
            "structural_guard": {"accepted": False, "normalized_diff_lines": 9},
            "source_retained": (
                f"{source_dir}/"
                "post-meta-source-family-sort-call-return-copy-local-max-text-copy.c"
            ),
            "pcdump_path": (
                f"{source_dir}/"
                "post-meta-source-family-sort-call-return-copy-local-max-text-copy.pcdump.txt"
            ),
        },
    ]


def _sort_issue1069_post_inline_classified() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "source_function": "mnDiagram_8023FC28",
        "status": "terminal",
        "score_rows": _sort_issue1069_score_rows(),
        "source_model_proof": {
            "source_family_synthesis": {
                "next_unsupported_source_family": (
                    SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY
                ),
                "next_unsupported_source_model": (
                    SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_MODEL
                ),
                "exhausted_dimensions": [
                    {
                        "dimension_id": (
                            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION
                        ),
                        "status": "scored-terminal",
                    }
                ],
            }
        },
    }


def _sort_issue1069_raw_combine_one_hit() -> dict:
    target_score = _sort_issue1069_target_score(hit_virtual="44")
    return {
        "kind": "debug-search-combine",
        "function": "mnDiagram_SortNamesByKOs",
        "combinations": [
            {
                "status": "ok",
                "candidate_id": "combine-post-inline-ig34-ig44-lower-drift",
                "parents": [
                    "post-meta-source-family-sort-init-indexed-write-name-total-locals",
                    "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
                ],
                "path": "build/sort/combine-post-inline-ig34-ig44-lower-drift.c",
                "source_retained": (
                    "build/sort/combine-post-inline-ig34-ig44-lower-drift.c"
                ),
                "pcdump_path": (
                    "build/sort/combine-post-inline-ig34-ig44-lower-drift.pcdump.txt"
                ),
                "target_score": target_score,
                "target_score_total": 9,
                "protected_preserved_count": 1,
                "protected_count": 2,
                "protected_assignments_satisfied": False,
                "missing_protected_assignments": [{"ig": 34, "phys": 27}],
                "satisfied_protected_assignments": [{"ig": 44, "phys": 25}],
                "normalized_diff_lines": 9,
                "structural_guard": {
                    "accepted": False,
                    "status": "lower-drift-protected-loss",
                    "normalized_diff_lines": 9,
                },
                "applied_hunks": [
                    {"hunk_id": "sort-ig34", "base_start": 10, "base_end": 11},
                    {"hunk_id": "sort-ig44", "base_start": 30, "base_end": 31},
                ],
                "score_result": {
                    "parsed_json": {
                        "target_score": target_score,
                        "source_retained": (
                            "build/sort/combine-post-inline-ig34-ig44-lower-drift.c"
                        ),
                        "pcdump_path": (
                            "build/sort/combine-post-inline-ig34-ig44-lower-drift.pcdump.txt"
                        ),
                    }
                },
            }
        ],
    }


def _sort_issue1069_continuation_payload() -> dict:
    return build_source_family_continuation_payload(
        _sort_issue1069_post_inline_classified(),
        [_sort_issue1069_raw_combine_one_hit()],
    )


def _sort_inline_leverage_strict_report() -> dict:
    return {
        "run_id": "mndiagram-987-sort-evidence",
        "scope": {
            "file": "src/melee/mn/mndiagram.c",
            "function": "mnDiagram_SortNamesByKOs",
        },
        "targets": [
            {
                "function": "mnDiagram_SortNamesByKOs",
                "source": "src/melee/mn/mndiagram.c",
            },
        ],
        "records": [
            {
                "run_id": "mndiagram-987-sort-evidence",
                "function": "mnDiagram_SortNamesByKOs",
                "unit": "src/melee/mn/mndiagram.c",
                "inline_name": "mnDiagram_SumNameKOs",
                "def_location": "tu",
                "def_file": "src/melee/mn/mndiagram.c:773",
                "is_static": True,
                "n_call_sites": 1,
                "baseline_pct": 99.35185,
                "deinlined_pct": 94.93519,
                "delta_fuzzy": 4.41666,
                "baseline_ndl": 0,
                "deinlined_ndl": 3,
                "delta_struct": 3,
                "verdict": "lever",
                "expansion_form": "scalar_assignment_splice",
                "shape_return": "scalar",
                "shape_body": "multi_statement",
                "shape_args": ["expression"],
                "n_statements": 7,
                "error": None,
                "evidence": {
                    "baseline_source": (
                        "build/diagnostics/mndiagram_987_rerun/"
                        "inline_leverage/evidence/"
                        "mnDiagram_SortNamesByKOs__mnDiagram_SumNameKOs/"
                        "baseline_source.c"
                    ),
                    "score": (
                        "build/diagnostics/mndiagram_987_rerun/"
                        "inline_leverage/evidence/"
                        "mnDiagram_SortNamesByKOs__mnDiagram_SumNameKOs/"
                        "score.json"
                    ),
                },
            },
        ],
    }


def _sort_post_ceiling_terminal() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal",
        "kind": "post-ceiling-baseline-escape",
        "evidence": {"final_force_phys": _sort_force()},
        "terminal_summary": {
            "status": "terminal",
            "kind": "no-post-ceiling-sort-source-family",
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": (
                "no-post-ceiling-sort-source-family/"
                "current-source-shape-ceiling"
            ),
            "candidate_count": 3,
            "scored_count": 3,
            "best_target_matched": 0,
            "best_target_targeted": 2,
            "best_target_virtual_distance": 2,
        },
    }


def _sort_inline_boundary_terminal() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "frontier_id": (
            "mnDiagram_SortNamesByKOs|"
            "inline-leverage-helper-boundary-continuation|"
            'inline="mnDiagram_SumNameKOs"|'
            'expansion="scalar_assignment_splice"|'
            'force={"34":27,"44":25}'
        ),
        "family_id": "inline-leverage-helper-boundary-continuation",
        "kind": "inline-leverage-helper-boundary-exhausted",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "inline-leverage-helper-boundary-exhausted/no-ig34-ig44-progress"
        ),
        "attempted_targets": _sort_force(),
        "protected_targets": {},
        "final_force_phys": _sort_force(),
        "inline_name": "mnDiagram_SumNameKOs",
        "expansion_form": "scalar_assignment_splice",
        "exhausted_dimensions": [
            {"dimension_id": "signature"},
            {"dimension_id": "local_declarations"},
            {"dimension_id": "loop_init"},
            {"dimension_id": "call_argument"},
            {"dimension_id": "return_local_materialization"},
            {"dimension_id": "scalar_assignment_splice_boundary"},
        ],
        "candidate_count": 6,
        "scored_count": 6,
    }


def _sort_estimated_source_model_frontier() -> dict:
    return {
        "frontier_id": "sort-estimated-recombine-frontier",
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "actionable",
        "terminal": False,
        "attempted_targets": _sort_force(),
        "protected_targets": _sort_force(),
        "final_force_phys": _sort_force(),
        "source_model_proof": {
            "source_family_synthesis": {
                "semantic_recombine": {
                    "ranked_candidates": [
                        {
                            "candidate_id": "estimated-recombine",
                            "dimension_id": "sort-semantic-dual-target-recombine",
                            "target_score_estimate": {
                                "matched": 2,
                                "targeted": 2,
                                "estimated": True,
                            },
                            "structural_guard": {
                                "accepted": True,
                                "estimated": True,
                            },
                        }
                    ],
                },
                "next_unsupported_source_model": SORT_ONE_HIT_UNSUPPORTED_MODEL,
            },
            "next_unsupported_source_model": SORT_ONE_HIT_UNSUPPORTED_MODEL,
        },
        "continuation": {
            "route": "sort-semantic-dual-target-recombine",
            "candidate_id": "estimated-recombine",
            "target_score_estimate": {
                "matched": 2,
                "targeted": 2,
                "estimated": True,
            },
        },
    }


def _sort_terminal_source_model_with_actionable_nested_semantic_recombine(
    *,
    scored: bool = False,
) -> dict:
    source_hunks = [
        {
            "hunk_id": "sort-semantic-recombine-ig34",
            "base_start": 120,
            "base_end": 121,
            "candidate_start": 120,
            "candidate_end": 121,
            "removed": ["old34;"],
            "added": ["new34;"],
        },
        {
            "hunk_id": "sort-semantic-recombine-ig44",
            "base_start": 130,
            "base_end": 131,
            "candidate_start": 130,
            "candidate_end": 131,
            "removed": ["old44;"],
            "added": ["new44;"],
        },
        {
            "hunk_id": "sort-semantic-recombine-bridge",
            "base_start": 140,
            "base_end": 141,
            "candidate_start": 140,
            "candidate_end": 141,
            "removed": ["old_bridge;"],
            "added": ["new_bridge;"],
        },
    ]
    payload = {
        "frontier_id": "sort-terminal-source-model-actionable-semantic",
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
        ),
        "attempted_targets": _sort_force(),
        "protected_targets": _sort_force(),
        "final_force_phys": _sort_force(),
        "source_model_proof": {
            "source_family_synthesis": {
                "post_ceiling_source_family_discovery": {
                    "semantic_recombine": {
                        "status": "actionable",
                        "ranked_candidates": [
                            {
                                "candidate_id": (
                                    "post-meta-sort-semantic-recombine-"
                                    "f32343df6df2"
                                ),
                                "dimension_id": (
                                    "sort-semantic-dual-target-recombine"
                                ),
                                "accepted": True,
                                "blockers": [],
                                "source_hunks": source_hunks,
                                "source_components": [
                                    {"component_id": "sort-selected-emission"}
                                ],
                                "target_score_estimate": {
                                    "matched": 2,
                                    "targeted": 2,
                                    "estimated": True,
                                    "virtual_distance": 0,
                                    "virtuals": {
                                        "34": {
                                            "expected": 27,
                                            "actual": 27,
                                            "matched": True,
                                        },
                                        "44": {
                                            "expected": 25,
                                            "actual": 25,
                                            "matched": True,
                                        },
                                    },
                                },
                            }
                        ],
                    }
                },
                "next_unsupported_source_model": SORT_ONE_HIT_UNSUPPORTED_MODEL,
            },
            "next_unsupported_source_model": SORT_ONE_HIT_UNSUPPORTED_MODEL,
        },
    }
    candidate = payload["source_model_proof"]["source_family_synthesis"][
        "post_ceiling_source_family_discovery"
    ]["semantic_recombine"]["ranked_candidates"][0]
    if scored:
        candidate.update({
            "source_retained": (
                "build/diagnostics/sort/semantic-recombine-scored.c"
            ),
            "pcdump_path": (
                "build/diagnostics/sort/semantic-recombine-scored.pcdump.txt"
            ),
            "target_score": {
                "matched": 2,
                "targeted": 2,
                "estimated": False,
                "virtual_distance": 0,
                "virtuals": {
                    "34": {
                        "expected": 27,
                        "actual": 27,
                        "matched": True,
                    },
                    "44": {
                        "expected": 25,
                        "actual": 25,
                        "matched": True,
                    },
                },
            },
            "structural_guard": {
                "accepted": True,
                "estimated": False,
                "normalized_diff_lines": 0,
            },
            "structural_guard_accepted": True,
            "real_score_authority": "protected-structural-synthesis",
        })
    return payload


def _sort_score_required_semantic_recombine_terminal() -> dict:
    terminal = _sort_terminal_source_model_with_actionable_nested_semantic_recombine()
    terminal["frontier_id"] = "sort-terminal-source-model-score-required-semantic"
    semantic = terminal["source_model_proof"]["source_family_synthesis"][
        "post_ceiling_source_family_discovery"
    ]["semantic_recombine"]
    semantic["status"] = "blocked"
    semantic["terminal_reason"] = "sort-semantic-dual-target-recombine-needs-real-score"
    semantic["terminal_blockers"] = []
    candidate = semantic["ranked_candidates"][0]
    candidate["accepted"] = False
    candidate["recommendation"] = "score-required"
    candidate["target_score"] = None
    candidate["blockers"] = ["no-scored-recombine-evidence"]
    candidate["structural_guard"] = {
        "accepted": False,
        "estimated": True,
        "status": "real-score-required",
    }
    candidate["structural_guard_accepted"] = False
    return terminal


def _sort_concrete_protected_loss_terminal() -> dict:
    evidence = {
        "status": "terminal",
        "reason": "manual-subhunk-protected-loss-exhausted",
        "terminal_blockers": [
            "manual-subhunk-protected-loss-exhausted",
            "lower-drift-candidates-lost-protected-assignments",
        ],
        "next_source_lever": SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL,
    }
    return {
        "frontier_id": "sort-concrete-protected-loss-terminal",
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "post-meta-gpr-one-hit-source-family-continuation-exhausted/"
            "protected-structural-ceiling"
        ),
        "attempted_targets": _sort_force(),
        "protected_targets": _sort_force(),
        "final_force_phys": _sort_force(),
        "real_score_authority": "protected-loss-negative-evidence",
        "protected_loss_negative_evidence": evidence,
        "terminal_blockers": evidence["terminal_blockers"],
        "source_model_proof": {
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "evidence_status": "artifact-synthesis-data",
                "protected_loss_negative_evidence": evidence,
                "terminal_blockers": evidence["terminal_blockers"],
                "exhausted_dimensions": [
                    {"dimension_id": "sort-semantic-protected-loss-repair"}
                ],
                "next_unsupported_source_model": (
                    SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL
                ),
            },
            "next_unsupported_source_model": SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL,
        },
    }


def _sort_raw_lower_drift_source_model_artifact() -> dict:
    candidates = []
    score_rows = []
    for index, candidate_id in enumerate(
        [
            "post-meta-source-family-sort-protected-loss-init-lifetime-ig34-null",
            "post-meta-source-family-sort-protected-loss-init-lifetime-ig44-copy",
            "post-meta-sort-natural-rewrite-protected-loss-init-lifetime-a",
            "post-meta-sort-natural-rewrite-protected-loss-init-lifetime-b",
        ],
        start=1,
    ):
        candidates.append({
            "candidate_id": candidate_id,
            "dimension_id": "sort-protected-loss-init-lifetime",
            "family": "post-meta-source-family-sort-protected-loss",
            "strategy": "protected-loss-init-lifetime",
            "source_hunks": [
                {
                    "hunk_id": f"lower-drift-{index}",
                    "old_start": 2100 + index,
                    "old_lines": ["old"],
                    "new_start": 2100 + index,
                    "new_lines": ["new"],
                }
            ],
        })
        score_rows.append({
            "candidate_id": candidate_id,
            "dimension_id": "sort-protected-loss-init-lifetime",
            "family": "post-meta-source-family-sort-protected-loss",
            "strategy": "protected-loss-init-lifetime",
            "classification": "structural-blocked",
            "target_matched": 0,
            "target_targeted": 2,
            "target_virtual_distance": 2,
            "source_retained": f"build/probes/{candidate_id}.c",
            "pcdump_path": f"build/probes/{candidate_id}.pcdump.txt",
            "source_hunks": candidates[-1]["source_hunks"],
            "blockers": [
                "protected-targets-not-jointly-preserved",
                "required-assignment-not-preserved:IG44->r25",
                "required-assignment-not-recovered:IG34->r27",
            ],
            "structural_guard": {
                "accepted": False,
                "reason": "protected-targets-not-jointly-preserved",
            },
            "target_score": {
                "matched": 0,
                "targeted": 2,
                "virtual_distance": 2,
                "virtuals": {
                    "34": {"expected": 27, "actual": None, "matched": False},
                    "44": {"expected": 25, "actual": 3, "matched": False},
                },
            },
        })
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "blocked",
        "reason": "score-rows-not-terminal-safe",
        "candidates": candidates,
        "score_rows": score_rows,
    }


def _sort_cross_tu_score_row(
    candidate_id: str,
    dimension_id: str,
    *,
    ig34_actual: int | None,
    ig44_actual: int | None,
    guard: str = "inline-boundary-toolchain-artifact",
) -> dict:
    ig34_matched = ig34_actual == 27
    ig44_matched = ig44_actual == 25
    matched = int(ig34_matched) + int(ig44_matched)
    return {
        "candidate_id": candidate_id,
        "dimension_id": dimension_id,
        "family": "post_meta_ceiling_sort_source_family_synthesis",
        "strategy": dimension_id,
        "classification": "structural-blocked",
        "target_matched": matched,
        "target_targeted": 2,
        "target_virtual_distance": 2 - matched,
        "source_retained": f"build/probes/{candidate_id}.c",
        "pcdump_path": f"build/probes/{candidate_id}.pcdump.txt",
        "source_hunks": [
            {
                "hunk_id": f"{candidate_id}-h001",
                "old_start": 930,
                "old_lines": ["old"],
                "new_start": 930,
                "new_lines": ["new"],
            }
        ],
        "structural_guard": {
            "accepted": False,
            "classification_primary": guard,
            "normalized_diff_lines": 5,
        },
        "target_score": {
            "matched": matched,
            "targeted": 2,
            "virtual_distance": 2 - matched,
            "virtuals": {
                "34": {
                    "expected": 27,
                    "actual": ig34_actual,
                    "matched": ig34_matched,
                },
                "44": {
                    "expected": 25,
                    "actual": ig44_actual,
                    "matched": ig44_matched,
                },
            },
        },
    }


def _sort_raw_cross_tu_source_model_artifact(*, with_context: bool = True) -> dict:
    rows = [
        _sort_cross_tu_score_row(
            "post-meta-source-family-sort-init-indexed-write-name-total-locals",
            "sort-init-indexed-write",
            ig34_actual=27,
            ig44_actual=31,
            guard="signature-type-mismatch",
        ),
        _sort_cross_tu_score_row(
            "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
            "sort-call-return-copy-local",
            ig34_actual=None,
            ig44_actual=25,
        ),
        _sort_cross_tu_score_row(
            "post-meta-source-family-sort-indexed-byte-cache-byte-cache",
            "sort-indexed-byte-cache",
            ig34_actual=None,
            ig44_actual=25,
        ),
    ]
    payload = {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "blocked",
        "reason": "score-rows-not-terminal-safe",
        "output_dir": (
            "build/diagnostics/mndiagram/source_model_cross_tu_symbol_linkage"
            if with_context
            else "build/diagnostics/mndiagram/source_model_legacy_rows"
        ),
        "candidates": [
            {
                "candidate_id": row["candidate_id"],
                "dimension_id": row["dimension_id"],
                "family": row["family"],
                "strategy": row["strategy"],
                "source_hunks": row["source_hunks"],
            }
            for row in rows
        ],
        "score_rows": rows,
    }
    if with_context:
        payload["context"] = {
            "force_phys": _sort_force(),
            "current_ceiling": {
                "next_unsupported_source_family": SORT_CROSS_TU_DIMENSION
            },
        }
    return payload


def _sort_model_only_cross_tu_blocked_artifact() -> dict:
    payload = _sort_raw_cross_tu_source_model_artifact(with_context=False)
    rows = payload["score_rows"]
    payload["output_dir"] = (
        "build/diagnostics/mndiagram_1082_1083_rerun/"
        "sort_current_ceiling_synthesis"
    )
    payload["next_unsupported_source_model"] = SORT_CROSS_TU_MODEL
    payload["context"] = {
        "force_phys": _sort_force(),
        "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
        "current_ceiling": {
            "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
            "attempted_equivalence_classes": [SORT_CROSS_TU_DIMENSION],
            "candidate_scores": rows,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": [SORT_CROSS_TU_DIMENSION],
                "candidate_scores": rows,
                "retained_scored_probes": rows,
                "source_hunks_by_candidate": [
                    {
                        "candidate_id": row["candidate_id"],
                        "dimension_id": SORT_CROSS_TU_DIMENSION,
                        "source_hunks": row["source_hunks"],
                    }
                    for row in rows
                ],
                "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
                "one_hit_summary": {
                    "one_hit_targets": ["34", "44"],
                    "protected_targets_not_jointly_preserved": True,
                },
            },
        },
    }
    return payload


def _sort_model_only_cross_tu_stale_continuation_artifact() -> dict:
    source_model = _sort_model_only_cross_tu_blocked_artifact()
    rows = source_model["context"]["current_ceiling"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    attempted = sorted(
        {
            row["dimension_id"]
            for row in rows
            if row.get("dimension_id") is not None
        }
    )
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "source_function": "mnDiagram_8023FC28",
        "status": "blocked",
        "terminal": False,
        "terminal_reason": "post-meta-source-family-continuation-needs-more-evidence",
        "terminal_blockers": ["score-row-error", "structural-guard-not-accepted"],
        "ranked_retained_candidates": rows,
        "source_model_proof": {
            "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": attempted,
                "retained_scored_probes": rows,
                "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
            },
        },
    }


def _sort_raw_cross_tu_after_whole_function_artifact() -> dict:
    payload = _sort_raw_cross_tu_source_model_artifact(with_context=False)
    payload["output_dir"] = (
        "build/diagnostics/mndiagram_1080_1081_rerun/"
        "sort_cross_after_whole_function"
    )
    payload["context"] = {
        "force_phys": _sort_force(),
        "current_ceiling": {
            "next_unsupported_source_family": (
                "sort-unbounded-tu-data-ownership-source-context"
            ),
            "next_unsupported_source_model": (
                "stale unbounded-TU data-ownership ceiling"
            ),
        },
    }
    payload["next_unsupported_source_family"] = (
        "sort-unbounded-tu-data-ownership-source-context"
    )
    payload["next_unsupported_source_model"] = (
        "stale unbounded-TU data-ownership ceiling"
    )
    payload["score_rows"].insert(
        0,
        {
            "candidate_id": "post-meta-sort-semantic-recombine-unscored",
            "dimension_id": "sort-semantic-dual-target-recombine",
            "source_retained": (
                "build/diagnostics/mndiagram_1080_1081_rerun/"
                "sort_cross_after_whole_function/probes/"
                "post-meta-sort-semantic-recombine-unscored.c"
            ),
            "target_matched": 0,
            "target_targeted": 2,
            "target_virtual_distance": 2,
        },
    )
    return payload


def _sort_cross_tu_recombine_artifact() -> dict:
    def combo(
        candidate_id: str,
        parents: list[str],
        *,
        ig34_actual: int | None,
        ig44_actual: int | None,
    ) -> dict:
        row = _sort_cross_tu_score_row(
            candidate_id,
            SORT_CROSS_TU_DIMENSION,
            ig34_actual=ig34_actual,
            ig44_actual=ig44_actual,
        )
        return {
            "candidate_id": candidate_id,
            "parents": parents,
            "status": "ok",
            "path": f"build/probes/{candidate_id}.c",
            "target_score": row["target_score"],
            "structural_guard": row["structural_guard"],
            "score_result": {
                "command": [
                    "melee-agent",
                    "debug",
                    "target",
                    "score-source",
                    f"build/probes/{candidate_id}.c",
                    "-f",
                    "mnDiagram_SortNamesByKOs",
                ]
            },
        }

    return {
        "base": "src/melee/mn/mndiagram.c",
        "candidates": [
            {"candidate_id": "ig34_name_total"},
            {"candidate_id": "ig44_max_text"},
            {"candidate_id": "ig44_byte_cache"},
            {"candidate_id": "ig44_cached_inputs"},
        ],
        "combinations": [
            combo(
                "combine-ig34_name_total-ig44_max_text",
                ["ig34_name_total", "ig44_max_text"],
                ig34_actual=None,
                ig44_actual=3,
            ),
            combo(
                "combine-ig34_name_total-ig44_byte_cache",
                ["ig34_name_total", "ig44_byte_cache"],
                ig34_actual=None,
                ig44_actual=25,
            ),
            combo(
                "combine-ig34_name_total-ig44_cached_inputs",
                ["ig34_name_total", "ig44_cached_inputs"],
                ig34_actual=None,
                ig44_actual=25,
            ),
            {
                "parents": ["ig44_max_text", "ig44_byte_cache"],
                "status": "skipped",
                "reason": "overlapping-source-hunks",
            },
        ],
    }


def _sort_protected_loss_recombine_artifact(
    *,
    required_assignments: dict[str, int] | None = None,
) -> dict:
    required = required_assignments or _sort_force()

    def combo(
        candidate_id: str,
        parents: list[str],
        *,
        ig34_actual: int | None,
        ig44_actual: int | None,
    ) -> dict:
        row = _sort_cross_tu_score_row(
            candidate_id,
            "sort-protected-loss-init-lifetime",
            ig34_actual=ig34_actual,
            ig44_actual=ig44_actual,
            guard="lower-drift-protected-loss",
        )
        return {
            "candidate_id": candidate_id,
            "parents": parents,
            "status": "ok",
            "path": f"build/probes/{candidate_id}.c",
            "pcdump_path": f"build/probes/{candidate_id}.pcdump.txt",
            "applied_hunks": row["source_hunks"],
            "target_score": row["target_score"],
            "structural_guard": row["structural_guard"],
            "score_result": {
                "command": [
                    "melee-agent",
                    "debug",
                    "target",
                    "score-source",
                    f"build/probes/{candidate_id}.c",
                    "-f",
                    "mnDiagram_SortNamesByKOs",
                    "--json",
                ]
            },
        }

    ranked = [
        {
            "candidate_id": "combine-ig34-live-ig44-alias",
            "parents": ["ig34_live", "ig44_alias"],
            "status": "ok",
            "path": "build/probes/combine-ig34-live-ig44-alias.c",
            "pcdump_path": "build/probes/combine-ig34-live-ig44-alias.pcdump.txt",
            "source_hunks": [{"hunk_id": "protected-recombine-h001"}],
            "protected_assignments_satisfied": False,
            "protected_preserved_count": 1,
            "protected_count": 2,
            "satisfied_protected_assignments": [{"ig": 34, "phys": 27}],
            "missing_protected_assignments": [{"ig": 44, "phys": 25}],
            "normalized_diff_lines": 9,
            "target_score_total": 65.0,
        }
    ]
    return {
        "base": "src/melee/mn/mndiagram.c",
        "candidates": [
            {"candidate_id": "ig34_live"},
            {"candidate_id": "ig44_alias"},
        ],
        "combinations": [
            {
                "parents": ["ig34_live", "ig34_value"],
                "status": "skipped",
                "reason": "overlapping-source-hunks",
            },
            combo(
                "combine-ig34-live-ig44-alias",
                ["ig34_live", "ig44_alias"],
                ig34_actual=27,
                ig44_actual=24,
            ),
            combo(
                "combine-ig34-value-ig44-alias",
                ["ig34_value", "ig44_alias"],
                ig34_actual=27,
                ig44_actual=24,
            ),
        ],
        "protected_structural_synthesis": {
            "status": "terminal-component-subset-exhausted",
            "candidate_found": False,
            "required_assignments": required,
            "ranked_candidates": ranked,
            "lower_drift_lost_protected_candidates": ranked,
            "terminal_blockers": [
                "lower-drift-candidates-lost-protected-assignments",
                "recombine-overlapping-source-hunks",
            ],
            "terminal_blocker": "protected-structural-synthesis-exhausted",
            "next_actions": [
                {"kind": "split-overlapping-components"},
                {"kind": "repair-lower-drift-protected-loss"},
            ],
        },
    }


def _sort_post_cross_tu_source_hypothesis_terminal_artifact() -> dict:
    rows = [
        _sort_cross_tu_score_row(
            "post-meta-sort-post-cross-tu-source-hypothesis-stable-name-locals",
            SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
            ig34_actual=27,
            ig44_actual=31,
            guard="post-cross-tu-one-hit",
        ),
        _sort_cross_tu_score_row(
            "post-meta-sort-post-cross-tu-source-hypothesis-dst-owner-emission-cursor",
            SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
            ig34_actual=24,
            ig44_actual=25,
            guard="post-cross-tu-one-hit",
        ),
    ]
    exhausted = [
        {
            "dimension_id": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
            "status": "scored-terminal",
            "candidate_ids": [row["candidate_id"] for row in rows],
        }
    ]
    source_hunks_by_candidate = [
        {
            "candidate_id": row["candidate_id"],
            "dimension_id": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
            "source_hunks": row["source_hunks"],
        }
        for row in rows
    ]
    synthesis = {
        "status": "synthesis-exhausted",
        "attempted_equivalence_classes": [
            SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION
        ],
        "exhausted_dimensions": exhausted,
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "scored_candidate_ids": [row["candidate_id"] for row in rows],
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "next_unsupported_source_model": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_MODEL,
        "next_unsupported_source_family": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY,
        "terminal_blockers": [
            {
                "reason": "protected-targets-not-jointly-preserved",
                "dimension_id": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
            }
        ],
    }
    proof = {
        "summary": "post-cross-TU source-hypothesis terminal proof",
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "source_family_synthesis": synthesis,
        "attempted_equivalence_classes": [
            SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION
        ],
        "next_unsupported_source_model": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_MODEL,
        "next_unsupported_source_family": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY,
    }
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "sort-post-cross-tu-selection-swap-source-hypothesis-exhausted/"
            "protected-targets-not-jointly-preserved"
        ),
        "family_id": "post_meta_ceiling_sort_source_family_synthesis",
        "next_unsupported_source_model": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_MODEL,
        "next_unsupported_source_family": SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY,
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "exhausted_dimensions": exhausted,
        "source_family_synthesis": synthesis,
        "source_model_proof": proof,
    }


def _sort_source_model_terminal_artifact(
    *,
    dimension: str,
    family: str,
    model: str,
    candidate_prefix: str,
) -> dict:
    rows = [
        _sort_cross_tu_score_row(
            f"{candidate_prefix}nested-text-total-decision",
            dimension,
            ig34_actual=24,
            ig44_actual=25,
        )
    ]
    exhausted = [
        {
            "dimension_id": dimension,
            "status": "scored-terminal",
            "candidate_ids": [row["candidate_id"] for row in rows],
        }
    ]
    source_hunks_by_candidate = [
        {
            "candidate_id": row["candidate_id"],
            "dimension_id": dimension,
            "source_hunks": row["source_hunks"],
        }
        for row in rows
    ]
    synthesis = {
        "status": "synthesis-exhausted",
        "attempted_equivalence_classes": [dimension],
        "exhausted_dimensions": exhausted,
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "scored_candidate_ids": [row["candidate_id"] for row in rows],
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "next_unsupported_source_model": model,
        "next_unsupported_source_family": family,
        "terminal_blockers": [
            {
                "reason": "protected-targets-not-jointly-preserved",
                "dimension_id": dimension,
            }
        ],
    }
    proof = {
        "summary": f"{dimension} terminal proof",
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "source_family_synthesis": synthesis,
        "attempted_equivalence_classes": [dimension],
        "next_unsupported_source_model": model,
        "next_unsupported_source_family": family,
    }
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            f"{dimension}-exhausted/protected-targets-not-jointly-preserved"
        ),
        "family_id": "post_meta_ceiling_sort_source_family_synthesis",
        "next_unsupported_source_model": model,
        "next_unsupported_source_family": family,
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "exhausted_dimensions": exhausted,
        "source_family_synthesis": synthesis,
        "source_model_proof": proof,
    }


def _sort_post_cross_tu_broader_natural_terminal_artifact() -> dict:
    return _sort_source_model_terminal_artifact(
        dimension=SORT_POST_CROSS_TU_BROADER_NATURAL_DIMENSION,
        family=SORT_POST_CROSS_TU_BROADER_NATURAL_FAMILY,
        model=SORT_POST_CROSS_TU_BROADER_NATURAL_MODEL,
        candidate_prefix="post-meta-sort-post-cross-tu-broader-natural-rewrite-",
    )


def _sort_post_broader_inline_boundary_terminal_artifact() -> dict:
    return _sort_source_model_terminal_artifact(
        dimension=SORT_POST_BROADER_INLINE_BOUNDARY_DIMENSION,
        family=SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY,
        model=SORT_POST_BROADER_INLINE_BOUNDARY_MODEL,
        candidate_prefix="post-meta-sort-post-broader-natural-inline-boundary-",
    )


def _sort_post_inline_boundary_selection_emission_terminal_artifact() -> dict:
    return _sort_source_model_terminal_artifact(
        dimension=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION,
        family=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY,
        model=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_MODEL,
        candidate_prefix="post-meta-sort-post-inline-boundary-selection-emission-",
    )


def _sort_stale_selection_swap_terminal_with_post_inline_attempt() -> dict:
    stale = _sort_post_cross_tu_source_hypothesis_terminal_artifact()
    proof = stale["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    attempted = [
        SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION,
    ]
    for target in (stale, proof, synthesis):
        target["attempted_equivalence_classes"] = attempted
        target["next_unsupported_source_model"] = SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_MODEL
        target["next_unsupported_source_family"] = (
            SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY
        )
    synthesis["exhausted_dimensions"] = [
        {
            "dimension_id": SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION,
            "status": "scored-terminal",
            "candidate_ids": [
                "post-meta-sort-post-inline-boundary-selection-emission-stale"
            ],
        }
    ]
    stale["terminal_reason"] = (
        "sort-post-cross-tu-selection-swap-source-hypothesis-exhausted/"
        "protected-targets-not-jointly-preserved"
    )
    return stale


def _sort_unbounded_tu_source_model_frontier() -> dict:
    return {
        "frontier_id": "sort-unbounded-tu-terminal",
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-ceiling-gpr-case-c-source-model-synthesis-proof",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
        ),
        "attempted_targets": _sort_force(),
        "protected_targets": {},
        "final_force_phys": _sort_force(),
        "source_model_proof": {
            "next_unsupported_source_model": (
                "Sort unbounded TU data-ownership source-context synthesis "
                "exhausted retained full-TU data declaration, ownership overlay, "
                "and nonlocal accessor rewrites without jointly recovering IG34/IG44."
            ),
            "next_unsupported_source_family": SORT_CROSS_TU_DIMENSION,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "evidence_status": "artifact-synthesis-data",
                "attempted_equivalence_classes": [
                    "sort-unbounded-tu-data-ownership-source-context"
                ],
                "exhausted_dimensions": [
                    {
                        "dimension_id": (
                            "sort-unbounded-tu-data-ownership-source-context"
                        )
                    }
                ],
            },
            "candidate_scores": [
                {
                    "candidate_id": (
                        "post-meta-sort-unbounded-tu-data-ownership-owner"
                    ),
                    "dimension_id": (
                        "sort-unbounded-tu-data-ownership-source-context"
                    ),
                }
            ],
        },
    }


def _draw_force() -> dict[str, int]:
    return {"37": 26, "32": 26}


def _draw_node_set_select_order_handoff(tmp_path: Path) -> dict:
    source_file = tmp_path / "retained_draw.c"
    pcdump = tmp_path / "retained_draw.pcdump"
    command = (
        "melee-agent debug select-order-search "
        "-f mnDiagram_DrawCellNumber "
        "--class 1 "
        "--target 'r32<r37' "
        f"--pcdump {pcdump} "
        f"--source-file {source_file} "
        "--include-transform-corpus "
        "--transform-force-phys 32:28,37:26,46:26 "
        "--json"
    )
    return {
        "function": "mnDiagram_DrawCellNumber",
        "case_c_order_repair": {
            "kind": "fpr-pcode-temp-case-c-order-repair",
            "function": "mnDiagram_DrawCellNumber",
            "class_id": 1,
            "target_ig": 37,
            "target_reg": "f26",
            "terminal_evidence": "all-wrong-register",
            "force_phys": "32:28,37:26,46:26",
            "target_order": "r32<r37",
            "source_file": str(source_file),
            "pcdump": str(pcdump),
            "routes": [
                {
                    "rank": 1,
                    "kind": "inspect-retained-first-divergence",
                    "command": (
                        "melee-agent debug inspect first-divergence "
                        f"{pcdump} -f mnDiagram_DrawCellNumber --class 1 "
                        "--force-phys 32:28,37:26,46:26 --source"
                    ),
                },
                {
                    "rank": 2,
                    "kind": "retained-source-select-order-repair",
                    "command": command,
                },
            ],
        },
    }


def _draw_select_order_case_c_terminal() -> dict:
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "ok",
        "class_id": 1,
        "target_orders": [[32, 37]],
        "terminal_exhaustion_summary": {
            "status": "blocked",
            "kind": "degree-zero-fpr-case-c-source-exhaustion",
            "dominant_blocker": "source-probes-exhausted",
            "terminal_blocker": "transform-family-exhausted",
            "force_phys_targets": {"32": 28, "37": 26, "46": 26},
            "blocker_targets": [37],
            "diagnostic_bucket_counts": {
                "force-phys-hit-target": 0,
                "force-phys-hit-protected": 0,
                "force-phys-hit-all": 0,
            },
            "best_retained_variant_count": 0,
            "next_source_lever_classes": [],
        },
    }


def _draw_issue998_force() -> dict[str, int]:
    return {"32": 28, "37": 26, "46": 26}


def _draw_issue998_source_model_proof() -> dict:
    dimensions = [
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
        "draw-col-offset-split-equivalence",
        "draw-row-offset-owner-scale",
        "draw-pcode-fsubs-protected-anchor",
    ]
    return {
        "summary": "Post-meta Draw expression continuation exhausted.",
        "register_class": "fpr",
        "target_anchors": [
            {"virtual": 32, "expected": 28, "actual": 26, "matched": False},
            {"virtual": 37, "expected": 26, "actual": 28, "matched": False},
            {"virtual": 46, "expected": 26, "actual": 1, "matched": False},
        ],
        "expression_anchors": [
            {
                "virtual": 32,
                "baseline_virtual": 32,
                "name": "col_offset",
                "expression": "y_spacing * (f32) col",
                "expected": 28,
                "actual": 26,
                "matched": False,
                "baseline_source": {
                    "source_file": "src/melee/mn/mndiagram.c",
                    "source_line": 2360,
                    "kind": "local",
                    "name": "col_offset",
                    "expression": "y_spacing * (f32) col",
                },
            },
            {
                "virtual": 37,
                "baseline_virtual": 37,
                "name": "row_offset",
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                "expected": 26,
                "actual": 28,
                "matched": False,
                "baseline_source": {
                    "source_file": "src/melee/mn/mndiagram.c",
                    "source_line": 2357,
                    "kind": "local",
                    "name": "row_offset",
                    "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                },
            },
            {
                "virtual": 46,
                "baseline_virtual": 46,
                "expression": "fsubs f46,f45,f44",
                "expected": 26,
                "actual": 1,
                "matched": False,
                "baseline_source": {
                    "source_file": "src/melee/mn/mndiagram.c",
                    "kind": "fpr-temp",
                    "expression": "fsubs f46,f45,f44",
                },
            },
        ],
        "residual_blocker_targets": [
            {"virtual": 32, "expected": 28, "actual": 26},
            {"virtual": 37, "expected": 26, "actual": 28},
            {"virtual": 46, "expected": 26, "actual": 1},
        ],
        "candidate_scores": [{"candidate_id": "draw-post-meta-plateau"}],
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "evidence_status": "artifact-synthesis-data",
            "attempted_equivalence_classes": dimensions,
            "exhausted_dimensions": [
                {"dimension_id": dimension, "status": "continuation-exhausted"}
                for dimension in dimensions
            ],
            "retained_scored_probes": [{"candidate_id": "draw-post-meta-plateau"}],
            "all_candidate_ids": ["draw-post-meta-plateau"],
            "candidate_count": 1,
            "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
        },
        "attempted_equivalence_classes": dimensions,
        "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
    }


def _draw_issue998_terminalized_continuation() -> dict:
    force = _draw_issue998_force()
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "terminal",
        "kind": "post-meta-source-family-continuation-proof",
        "family_id": "post-ceiling-source-model-proof",
        "terminal": True,
        "terminal_reason": (
            "post-meta-fpr-expression-hit-continuation-exhausted/"
            "protected-anchor-ceiling"
        ),
        "final_force_phys": force,
        "attempted_targets": force,
        "terminal_summary": {
            "status": "terminal",
            "kind": "no-post-ceiling-draw-source-family",
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": (
                "no-post-ceiling-draw-source-family/"
                "current-source-shape-ceiling"
            ),
            "best_target_matched": 0,
            "best_target_targeted": 3,
            "best_expression_matched": 1,
            "best_expression_targeted": 3,
            "target_anchors": [
                {"baseline_virtual": 32, "expected": 28},
                {"baseline_virtual": 37, "expected": 26},
                {"baseline_virtual": 46, "expected": 26},
            ],
        },
        "score_classification": {
            "candidates": [{"candidate_id": "draw-post-meta-plateau"}],
        },
        "source_model_proof": _draw_issue998_source_model_proof(),
    }


def _draw_issue998_route_less_plateau_frontier() -> dict:
    force = _draw_issue998_force()
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "mnDiagram_DrawCellNumber|post-ceiling-source-model-proof|plateau",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "actionable",
        "terminal": False,
        "actionable": True,
        "continuation": None,
        "attempted_targets": force,
        "protected_targets": force,
        "final_force_phys": force,
        "source_model_proof": _draw_issue998_source_model_proof(),
    }


def _draw_issue998_compat_terminal_frontier() -> dict:
    force = _draw_issue998_force()
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "mnDiagram_DrawCellNumber|post-ceiling-baseline-escape|terminal",
        "family_id": "post-ceiling-baseline-escape",
        "kind": "no-post-ceiling-draw-source-family",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": "no-post-ceiling-draw-source-family/current-source-shape-ceiling",
        "suppression_family": "post-ceiling-baseline-escape",
        "attempted_targets": force,
        "protected_targets": {},
        "final_force_phys": force,
    }


def _sort_stale_retained_frontier(function="mnDiagram_SortNamesByKOs"):
    return {
        "function": function,
        "retained_case_c_window_order_continuation_summary": {
            "status": "source-actionable",
            "kind": "retained-source-case-c-implicit-address-temp",
            "family_id": "retained_gpr_case_c_window_order_continuation",
            "attempted_targets": {"34": 27},
            "protected_targets": {"44": 25},
            "final_force_phys": _sort_force(),
            "command_hints": [
                "melee-agent debug target score-source build/probes/sort.c "
                "--function mnDiagram_SortNamesByKOs --json"
            ],
        },
    }


def _sort_window_order_end_pointer_terminal(function="mnDiagram_SortNamesByKOs"):
    return {
        "function": function,
        "retained_case_c_window_order_continuation_summary": {
            "status": "blocked",
            "kind": "retained-source-case-c-implicit-address-temp",
            "family_id": "retained_gpr_case_c_window_order_continuation",
            "terminal_blocker": (
                "ranked-indexed-byte-window-order-probes-exhausted"
            ),
            "attempted_targets": {"34": 27},
            "protected_targets": {"44": 25},
            "final_force_phys": _sort_force(),
            "evaluated_probe_count": 1,
            "exact_count": 0,
            "protected_negative_count": 1,
            "target_score": {
                "matched": 1,
                "targeted": 2,
                "virtuals": {
                    "34": {"expected": 27, "actual": 27, "matched": True},
                    "44": {"expected": 25, "actual": 27, "matched": False},
                },
            },
        },
    }


def _sort_copy_survived_terminal(function="mnDiagram_SortNamesByKOs"):
    return {
        "function": function,
        "copy_survived_repair": {
            "status": "terminal-blocker",
            "trace_status": "copy-found",
            "transform_category": "copy-survived",
            "register_class": "gpr",
            "class_id": 0,
            "from_ig_idx": 34,
            "to_ig_idx": 41,
            "from_assigned_reg": 24,
            "to_assigned_reg": 28,
            "scored_count": 3,
            "failed_count": 1,
            "pointer_reset_probe_count": 4,
            "pointer_reset_failed_count": 1,
            "terminal_blocker": (
                "copy-survived pointer-reset repair exhausted scored "
                "source-visible reset probes"
            ),
        },
    }


def _sort_copy_survived_parent(tmp_path: Path) -> dict:
    source = tmp_path / "pointer-walk.c"
    pcdump = tmp_path / "pointer-walk.pcdump.txt"
    routes = []
    for rank, kind, var in (
        (1, "node-set-split-generated-local", "ll_probe_iter_0"),
        (2, "node-set-split-pointer-base", "dst"),
        (3, "node-set-split-loop-counter", "i"),
    ):
        routes.append({
            "rank": rank,
            "kind": kind,
            "var": var,
            "target_ig": 34,
            "current_reg": "r0",
            "target_reg": "r27",
            "force_phys": "34:27,44:25",
            "command": (
                "melee-agent debug solve node-set-split "
                "-f mnDiagram_SortNamesByKOs --class gpr "
                f"--source-file {source} --ig 34 --current-reg r0 "
                f"--target-reg r27 --var {var} --json "
                "--force-phys 34:27,44:25"
            ),
        })
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "trace_copy": {
            "status": "copy-found",
            "transform_category": "copy-survived",
            "register_class": "gpr",
            "class_id": 0,
            "from_ig_idx": 64,
            "to_ig_idx": 34,
            "from_assigned_reg": 27,
            "to_assigned_reg": 0,
        },
        "copy_survived_repair": {
            "status": "source-actionable",
            "trace_status": "copy-found",
            "transform_category": "copy-survived",
            "register_class": "gpr",
            "class_id": 0,
            "from_ig_idx": 64,
            "to_ig_idx": 34,
            "from_assigned_reg": 27,
            "to_assigned_reg": 0,
            "scored_count": 4,
            "failed_count": 0,
            "best_variant": {
                "operator": "pointer-walk-loop",
                "continuation": {
                    "kind": "copy-survived-generated-local-continuation",
                    "status": "route-available",
                    "source_retained": str(source),
                    "pcdump_path": str(pcdump),
                    "routes": routes,
                },
            },
        },
    }


def _sort_node_set_exhausted(var_name: str) -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "exhausted",
        "scored_count": 1,
        "wrong_register_exhausted": True,
        "terminal_reason": "all-wrong-register",
        "request": {
            "function": "mnDiagram_SortNamesByKOs",
            "class_id": 0,
            "target_ig": 34,
            "current_reg": "r0",
            "target_reg": "r27",
            "var_name": var_name,
            "target_regs": ["r27"],
        },
        "candidates": [
            {
                "candidate_id": f"node-split-{var_name}-ig34",
                "objective": {
                    "function": "mnDiagram_SortNamesByKOs",
                    "class_id": 0,
                    "target_ig": 34,
                    "target_reg": "r27",
                    "target_reg_num": 27,
                    "assigned_reg": 0,
                    "status": "wrong-register",
                    "target_score": {
                        "matched": 1,
                        "targeted": 2,
                        "virtuals": {
                            "34": {
                                "expected": 27,
                                "actual": 0,
                                "hit": False,
                                "matched": False,
                            },
                            "44": {
                                "expected": 25,
                                "actual": 25,
                                "hit": True,
                                "matched": True,
                            },
                        },
                    },
                },
            }
        ],
    }


def _sort_generated_local_exhausted_without_target_progress() -> dict:
    payload = _sort_node_set_exhausted("ll_probe_iter_0")
    payload["wrong_register_exhausted"] = False
    payload["wrong_register_or_compile_failed_exhausted"] = False
    payload["terminal_reason"] = None
    payload["pending_count"] = 0
    payload["stop_reason"] = None
    payload["stop_condition"] = None
    payload["objective_counts"] = {
        "wrong-register": 1,
        "spill-regression": 1,
    }
    payload["candidates"].append({
        "candidate_id": "node-split-generated-pointer-walk-base-ll_probe_iter_0-ig34",
        "objective": {
            "function": "mnDiagram_SortNamesByKOs",
            "class_id": 0,
            "target_ig": 34,
            "target_reg": "r27",
            "target_reg_num": 27,
            "assigned_reg": 0,
            "status": "spill-regression",
            "target_score": {
                "matched": 0,
                "targeted": 2,
                "virtuals": {
                    "34": {
                        "expected": 27,
                        "actual": 0,
                        "hit": False,
                        "matched": False,
                    },
                    "44": {
                        "expected": 25,
                        "actual": 26,
                        "hit": False,
                        "matched": False,
                    },
                },
            },
        },
    })
    return payload


def _post_ceiling_continuation_actionable(tmp_path: Path) -> dict:
    source_file = tmp_path / "sort.c"
    pcdump = tmp_path / "sort.pcdump.txt"
    command = (
        "melee-agent debug select-order-search "
        "-f mnDiagram_SortNamesByKOs --class 0 "
        "--target 'r34<r44' "
        f"--pcdump {pcdump} --source-file {source_file} "
        "--force-phys 34:27,44:25 --json"
    )
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "post_ceiling_continuation_summary": {
            "status": "source-actionable",
            "kind": "post-ceiling-baseline-escape-continuation",
            "family_id": "post-ceiling-baseline-escape-continuation",
            "suppression_family": "post-ceiling-baseline-escape-continuation",
            "final_force_phys": _sort_force(),
            "ranked_candidates": [
                {
                    "candidate_id": "post-ceiling-sort-init-pointer-walk",
                    "continuation": {
                        "route": "retained-source-select-order-repair",
                        "command": command,
                        "source_retained": str(source_file),
                        "pcdump_path": str(pcdump),
                    },
                }
            ],
            "blockers": [],
        },
    }


def _post_ceiling_continuation_terminal() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "post_ceiling_continuation_summary": {
            "status": "terminal",
            "kind": "post-ceiling-continuation-exhausted",
            "terminal_reason": (
                "post-ceiling-continuation-exhausted/"
                "all-candidate-routes-unsupported"
            ),
            "family_id": "post-ceiling-baseline-escape-continuation",
            "suppression_family": "post-ceiling-baseline-escape-continuation",
            "final_force_phys": _sort_force(),
            "candidate_count": 1,
            "scored_count": 1,
            "blockers": [
                {
                    "candidate_id": "post-ceiling-sort-init-pointer-walk",
                    "blocker": "no-source-actionable-route",
                }
            ],
        },
    }


def _sort_source_model_terminal_proof() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal",
        "terminal_summary": {
            "status": "terminal",
            "kind": "no-post-ceiling-sort-source-family",
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": (
                "no-post-ceiling-sort-source-family/"
                "current-source-shape-ceiling"
            ),
            "candidate_count": 2,
            "best_candidate_id": "post-ceiling-sort-init-pointer-walk",
            "best_target_matched": 0,
            "best_target_targeted": 2,
            "best_target_virtual_distance": 2,
            "target_anchors": [
                {
                    "virtual": 34,
                    "baseline_virtual": 34,
                    "name": "ig34",
                    "expected": 27,
                    "actual": None,
                    "matched": False,
                },
                {
                    "virtual": 44,
                    "baseline_virtual": 44,
                    "name": "ig44",
                    "expected": 25,
                    "actual": None,
                    "matched": False,
                },
            ],
            "final_force_phys": _sort_force(),
        },
        "candidates": [
            {
                "candidate_id": "post-ceiling-sort-init-pointer-walk",
                "family": "post_ceiling_sort_loop_shape",
                "strategy": "init-pointer-walk",
                "priority": 90,
                "rationale": "Rewrite the initialization loop pointer progression.",
                "expected_effect": "move dst_iter/tp lifetime products",
                "novelty_reason": "whole-loop source shape",
            },
            {
                "candidate_id": "post-ceiling-sort-swap-materialization",
                "family": "post_ceiling_sort_swap_materialization",
                "strategy": "selected-slot-materialization",
                "priority": 80,
                "rationale": "Materialize the selected name slot before the move.",
                "expected_effect": "test selected-slot address/copy source boundary",
                "novelty_reason": "changes selected-slot baseline",
            },
        ],
        "score_classification": {
            "best_target_matched": 0,
            "best_target_targeted": 2,
            "best_candidate_id": "post-ceiling-sort-init-pointer-walk",
            "candidates": [
                {
                    "candidate_id": "post-ceiling-sort-init-pointer-walk",
                    "classification": "structural-preserving",
                    "target_matched": 0,
                    "target_targeted": 2,
                    "target_virtual_distance": 2,
                    "target_score": {
                        "matched": 0,
                        "targeted": 2,
                        "virtuals": {
                            "34": {"expected": 27, "actual": 24},
                            "44": {"expected": 25, "actual": 27},
                        },
                    },
                },
                {
                    "candidate_id": "post-ceiling-sort-swap-materialization",
                    "classification": "recoverable-downhill",
                    "target_matched": 0,
                    "target_targeted": 2,
                    "target_virtual_distance": 2,
                    "target_score": {
                        "matched": 0,
                        "targeted": 2,
                        "virtuals": {
                            "34": {"expected": 27, "actual": 4},
                            "44": {"expected": 25, "actual": 31},
                        },
                    },
                },
            ],
        },
        "post_ceiling_final_summary": {
            "residual_blocker_targets": [
                {"virtual": 34, "expected": 27, "actual": 24},
                {"virtual": 44, "expected": 25, "actual": 27},
            ],
        },
        "evidence": {
            "retained_frontiers": {
                "closed_families": [
                    "copy-survived-pointer-reset",
                    "retained-source-select-order-repair",
                ],
            },
            "suppressed_families": ["node-set-split", "source-owner-backtracking"],
        },
    }


def _sort_source_model_terminal_proof_with_synthesis() -> dict:
    payload = _sort_source_model_terminal_proof()
    source_family_ids = [
        "post-ceiling-source-family-sort-init-indexed-write",
        "post-ceiling-source-family-sort-indexed-byte-cache",
        "post-ceiling-source-family-sort-call-return-copy-local",
        "post-ceiling-source-family-sort-swap-slot-lvalue",
    ]
    dimensions = [
        {
            "dimension_id": "sort-init-indexed-write",
            "neighborhood_id": "sort-init-pointer-walk",
            "generated_candidate_ids": [source_family_ids[0]],
            "scored_candidate_ids": [source_family_ids[0]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
        {
            "dimension_id": "sort-indexed-byte-cache",
            "neighborhood_id": "sort-max-idx-indexed-byte",
            "generated_candidate_ids": [source_family_ids[1]],
            "scored_candidate_ids": [source_family_ids[1]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
        {
            "dimension_id": "sort-call-return-copy-local",
            "neighborhood_id": "sort-call-return-copy",
            "generated_candidate_ids": [],
            "scored_candidate_ids": [source_family_ids[2]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
        {
            "dimension_id": "sort-swap-slot-lvalue",
            "neighborhood_id": "sort-swap-materialization",
            "generated_candidate_ids": [],
            "scored_candidate_ids": [source_family_ids[3]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
    ]
    source_family_score_rows = []
    for candidate_id in source_family_ids:
        target_progress = candidate_id in {
            "post-ceiling-source-family-sort-indexed-byte-cache",
            "post-ceiling-source-family-sort-call-return-copy-local",
        }
        source_family_score_rows.append({
            "candidate_id": candidate_id,
            "classification": (
                "target-progress" if target_progress else "structural-preserving"
            ),
            "expression_matched": 0,
            "expression_targeted": 2,
            "expression_virtual_distance": 2,
            "target_matched": 1 if target_progress else 0,
            "target_targeted": 2,
            "target_virtual_distance": 1 if target_progress else 2,
            "expression_score": {
                "register_class": "gpr",
                "derived_from_baseline": True,
                "matched": 0,
                "targeted": 2,
                "virtual_distance": 2,
                "false_positive_virtual_id_hit_count": (
                    1 if target_progress else 0
                ),
                "virtuals": {
                    "34": {
                        "expected": 27,
                        "actual": 24,
                        "matched": False,
                        "baseline_source": {
                            "name": "ig34",
                            "expression": "sort gpr source span",
                        },
                    },
                    "44": {
                        "expected": 25,
                        "actual": 27,
                        "matched": False,
                    },
                },
            },
            "target_score": {
                "matched": 1 if target_progress else 0,
                "targeted": 2,
                "virtual_distance": 1 if target_progress else 2,
                "virtuals": {
                    "34": {
                        "expected": 27,
                        "actual": 24,
                        "matched": target_progress,
                    },
                    "44": {
                        "expected": 25,
                        "actual": 27,
                        "matched": False,
                    },
                },
            },
            "target_virtuals": {
                "34": {
                    "expected": 27,
                    "actual": 24,
                    "matched": target_progress,
                },
                "44": {"expected": 25, "actual": 27, "matched": False},
            },
        })
    plateau = {
        "status": "terminal",
        "kind": "post-ceiling-source-family-progress-plateau",
        "terminal_reason": (
            "post-ceiling-source-family-progress-plateau/"
            "current-source-shape-ceiling"
        ),
        "source_family_candidate_ids": source_family_ids,
        "source_family_score_rows": source_family_score_rows,
        "progress_candidate_ids": [],
        "next_unsupported_source_model": (
            "fixture: full transform-corpus adapter remains the next "
            "unsupported Sort source model"
        ),
    }
    payload["terminal_summary"]["source_family_progress_plateau"] = plateau
    payload["post_ceiling_source_family_plateau_summary"] = plateau
    payload["post_ceiling_source_family_discovery"] = {
        "status": "terminal",
        "kind": "post-ceiling-source-family-discovery",
        "family_id": "post-ceiling-source-family-discovery",
        "function": "mnDiagram_SortNamesByKOs",
        "final_force_phys": _sort_force(),
        "source_family_dimensions": dimensions,
        "generated_family_dimensions": dimensions,
        "probes": [
            {
                "candidate_id": source_family_ids[0],
                "probe_id": source_family_ids[0],
                "dimension_id": "sort-init-indexed-write",
                "source_hunks": [
                    {
                        "hunk_id": "sort-init-indexed-write-h0",
                        "old_start": 10,
                        "old_lines": ["*dst_iter = (u8) n;"],
                        "new_start": 10,
                        "new_lines": ["dst[n] = (u8) n;"],
                    }
                ],
            },
            {
                "candidate_id": source_family_ids[1],
                "probe_id": source_family_ids[1],
                "dimension_id": "sort-indexed-byte-cache",
                "source_hunks": [
                    {
                        "hunk_id": "sort-indexed-byte-cache-h0",
                        "old_start": 30,
                        "old_lines": ["dst[max_idx]"],
                        "new_start": 30,
                        "new_lines": ["max_name = dst[max_idx]"],
                    }
                ],
            },
        ],
        "retained_scored_probes": [
            {
                "candidate_id": source_family_ids[2],
                "source_retained": "build/probes/sort-call-return-copy-local.c",
                "pcdump_path": "build/probes/sort-call-return-copy-local.pcdump.txt",
                "source_hunks": [
                    {
                        "hunk_id": "sort-call-return-copy-local-h0",
                        "old_start": 40,
                        "old_lines": ["mnDiagram_GetNameText(j)"],
                        "new_start": 40,
                        "new_lines": ["post_ceiling_j_text_copy"],
                    }
                ],
                "target_score": {"matched": 0, "targeted": 2},
            },
            {
                "candidate_id": source_family_ids[1],
                "source_retained": "build/probes/sort-indexed-byte-cache.c",
                "pcdump_path": "build/probes/sort-indexed-byte-cache.pcdump.txt",
                "target_score": {"matched": 1, "targeted": 2},
            }
        ],
        "missing_inputs": [
            {"input": "pcdump_path", "reason": "fixture-omitted"}
        ],
        "exhausted_dimensions": dimensions,
        "skipped_dimensions": [
            {
                "dimension_id": "sort-transform-corpus-adapter",
                "reason": "not-owned-by-this-issue",
            }
        ],
    }
    return payload


def _draw_source_model_terminal_proof() -> dict:
    target_anchors = [
        {
            "virtual": 32,
            "baseline_virtual": 32,
            "name": "col_offset",
            "expression": "y_spacing * (f32) col",
            "expected": 28,
            "actual": None,
            "matched": False,
        },
        {
            "virtual": 37,
            "baseline_virtual": 37,
            "name": "row_offset",
            "expression": "HSD_JObjGetTranslationY(jobj2) - base",
            "expected": 26,
            "actual": 28,
            "matched": False,
        },
        {
            "virtual": 46,
            "baseline_virtual": 46,
            "name": None,
            "expression": "fsubs f46,f45,f44",
            "expected": 26,
            "actual": 1,
            "matched": False,
        },
    ]
    expression_virtuals = {
        "32": {
            "baseline_virtual": 32,
            "expected": 28,
            "signature": {
                "kind": "source-expression",
                "source_kind": "local",
                "name": "col_offset",
                "expression": "y_spacing * (f32) col",
            },
            "baseline_source": {
                "kind": "local",
                "confidence": "fpr-expression-order",
                "name": "col_offset",
                "type": "f32",
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2564,
                "source_col": 18,
                "expression": "y_spacing * (f32) col",
            },
            "candidate_virtual": 33,
            "actual": 26,
            "virtual_id_actual": 1,
            "matched": False,
            "renumbered": True,
        },
        "37": {
            "baseline_virtual": 37,
            "expected": 26,
            "signature": {
                "kind": "source-expression",
                "source_kind": "local",
                "name": "row_offset",
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
            },
            "baseline_source": {
                "kind": "local",
                "confidence": "fpr-expression-order",
                "name": "row_offset",
                "type": "f32",
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2561,
                "source_col": 18,
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
            },
            "candidate_virtual": 37,
            "actual": 28,
            "virtual_id_actual": 28,
            "matched": False,
            "renumbered": False,
        },
        "46": {
            "baseline_virtual": 46,
            "expected": 26,
            "signature": {
                "kind": "first-def",
                "source_kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
            "baseline_source": {
                "kind": "fpr-temp",
                "confidence": "pcode-first-def",
                "source_file": "src/melee/mn/mndiagram.c",
                "expression": "fsubs f46,f45,f44",
            },
            "candidate_virtual": 46,
            "actual": 1,
            "virtual_id_actual": 1,
            "matched": False,
            "renumbered": False,
        },
    }
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "terminal",
        "terminal_summary": {
            "status": "terminal",
            "kind": "no-post-ceiling-draw-source-family",
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": (
                "no-post-ceiling-draw-source-family/"
                "current-source-shape-ceiling"
            ),
            "candidate_count": 3,
            "scored_count": 3,
            "best_candidate_id": "post-ceiling-digit-anim-callarg-block",
            "best_expression_matched": 0,
            "best_expression_targeted": 3,
            "best_expression_virtual_distance": 3,
            "best_target_matched": 0,
            "best_target_targeted": 3,
            "best_target_virtual_distance": 3,
            "target_anchors": target_anchors,
            "final_force_phys": {"32": 28, "37": 26, "46": 26},
        },
        "candidates": [
            {
                "candidate_id": "post-ceiling-paired-offset-block",
                "family": "post_ceiling_statement_grouping",
                "strategy": "paired-offset-block",
                "priority": 100,
                "rationale": "Group the column and row offset computations.",
                "expected_effect": "alter row/column FPR lifetime boundary",
                "novelty_reason": "paired statement grouping",
            },
            {
                "candidate_id": "post-ceiling-paired-visible-owner",
                "family": "post_ceiling_paired_owner_baseline",
                "strategy": "paired-visible-owner",
                "priority": 90,
                "rationale": "Materialize visible row/column owners.",
                "expected_effect": "test row/column source owner lifetimes",
                "novelty_reason": "paired visible owner baseline",
            },
            {
                "candidate_id": "post-ceiling-digit-anim-callarg-block",
                "family": "post_ceiling_call_temp_materialization",
                "strategy": "digit-anim-callarg-block",
                "priority": 80,
                "rationale": "Materialize digit animation call argument.",
                "expected_effect": "test helper-call argument pressure",
                "novelty_reason": "targets the digit-call FPR anchor",
            },
        ],
        "score_classification": {
            "best_expression_matched": 0,
            "best_expression_targeted": 3,
            "best_target_matched": 0,
            "best_target_targeted": 3,
            "best_candidate_id": "post-ceiling-digit-anim-callarg-block",
            "candidates": [
                {
                    "candidate_id": "post-ceiling-digit-anim-callarg-block",
                    "classification": "recoverable-downhill",
                    "expression_matched": 0,
                    "expression_targeted": 3,
                    "expression_virtual_distance": 3,
                    "target_matched": 0,
                    "target_targeted": 3,
                    "target_virtual_distance": 3,
                    "expression_score": {
                        "register_class": "fpr",
                        "derived_from_baseline": True,
                        "matched": 0,
                        "targeted": 3,
                        "virtual_distance": 3,
                        "renumbered": 1,
                        "virtuals": expression_virtuals,
                    },
                    "target_score": {
                        "matched": 0,
                        "targeted": 3,
                        "virtual_distance": 3,
                        "virtuals": {
                            "32": {"expected": 28, "actual": 1},
                            "37": {"expected": 26, "actual": 28},
                            "46": {"expected": 26, "actual": 1},
                        },
                    },
                },
                {
                    "candidate_id": "post-ceiling-paired-offset-block",
                    "classification": "recoverable-downhill",
                    "expression_matched": 0,
                    "expression_targeted": 3,
                    "expression_virtual_distance": 3,
                    "target_matched": 0,
                    "target_targeted": 3,
                    "target_virtual_distance": 3,
                    "expression_score": {
                        "register_class": "fpr",
                        "matched": 0,
                        "targeted": 3,
                        "virtual_distance": 3,
                    },
                    "target_score": {
                        "matched": 0,
                        "targeted": 3,
                        "virtual_distance": 3,
                    },
                },
                {
                    "candidate_id": "post-ceiling-paired-visible-owner",
                    "classification": "recoverable-downhill",
                    "expression_matched": 0,
                    "expression_targeted": 3,
                    "expression_virtual_distance": 3,
                    "target_matched": 0,
                    "target_targeted": 3,
                    "target_virtual_distance": 3,
                    "expression_score": {
                        "register_class": "fpr",
                        "matched": 0,
                        "targeted": 3,
                        "virtual_distance": 3,
                    },
                    "target_score": {
                        "matched": 0,
                        "targeted": 3,
                        "virtual_distance": 3,
                    },
                },
            ],
        },
        "post_ceiling_final_summary": {
            "residual_blocker_targets": [
                {"virtual": 32, "expected": 28, "actual": 1},
                {"virtual": 37, "expected": 26, "actual": 28},
                {"virtual": 46, "expected": 26, "actual": 1},
            ],
        },
    }


def _draw_source_model_terminal_proof_with_synthesis() -> dict:
    payload = _draw_source_model_terminal_proof()
    source_family_ids = [
        "post-ceiling-source-family-draw-col-cast-product-local",
        "post-ceiling-source-family-draw-row-translation-scale-split",
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
    ]
    dimensions = [
        {
            "dimension_id": "draw-col-cast-product-local",
            "neighborhood_id": "draw-col-offset-product",
            "description": "materialize the col cast and product as source locals",
            "operations": ["cast-local", "product-local"],
            "generated_candidate_ids": [source_family_ids[0]],
            "scored_candidate_ids": [source_family_ids[0]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
        {
            "dimension_id": "draw-row-translation-scale-split",
            "neighborhood_id": "draw-row-offset-scale",
            "description": "split row translation delta from the row scale product",
            "operations": ["translation-delta-local", "scale-product-local"],
            "generated_candidate_ids": [source_family_ids[1]],
            "scored_candidate_ids": [source_family_ids[1]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
        {
            "dimension_id": "draw-digit-callarg-fsubs-temp",
            "neighborhood_id": "draw-digit-callarg",
            "description": "materialize a digit animation fsubs-style call argument",
            "operations": ["callarg-temp", "fsubs-temp"],
            "generated_candidate_ids": [source_family_ids[2]],
            "scored_candidate_ids": [source_family_ids[2]],
            "status": "scored-terminal",
            "exhaustion_reason": "retained-source-family-scored-no-progress",
        },
    ]
    source_family_score_rows = [
        {
            "candidate_id": candidate_id,
            "classification": "recoverable-downhill",
            "expression_matched": 0,
            "expression_targeted": 3,
            "expression_virtual_distance": 3,
            "target_matched": 0,
            "target_targeted": 3,
            "target_virtual_distance": 3,
        }
        for candidate_id in source_family_ids
    ]
    plateau = {
        "status": "terminal",
        "kind": "post-ceiling-source-family-progress-plateau",
        "terminal_reason": (
            "post-ceiling-source-family-progress-plateau/"
            "current-source-shape-ceiling"
        ),
        "source_family_candidate_ids": source_family_ids,
        "source_family_score_rows": source_family_score_rows,
        "progress_candidate_ids": [],
        "next_unsupported_source_model": (
            "fixture: broader Draw FPR expression source model remains "
            "unsupported"
        ),
    }
    payload["terminal_summary"]["source_family_progress_plateau"] = plateau
    payload["post_ceiling_source_family_plateau_summary"] = plateau
    payload["post_ceiling_source_family_discovery"] = {
        "status": "terminal",
        "kind": "post-ceiling-source-family-discovery",
        "family_id": "post-ceiling-source-family-discovery",
        "function": "mnDiagram_DrawCellNumber",
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "source_family_dimensions": dimensions,
        "generated_family_dimensions": dimensions,
        "probes": [
            {
                "candidate_id": source_family_ids[0],
                "probe_id": source_family_ids[0],
                "dimension_id": "draw-col-cast-product-local",
                "source_hunks": [
                    {
                        "hunk_id": "draw-col-cast-product-local-h0",
                        "old_start": 2564,
                        "old_lines": ["col_offset = y_spacing * (f32) col;"],
                        "new_start": 2564,
                        "new_lines": [
                            "post_ceiling_col = y_spacing * (f32) col;"
                        ],
                    }
                ],
            },
            {
                "candidate_id": source_family_ids[1],
                "probe_id": source_family_ids[1],
                "dimension_id": "draw-row-translation-scale-split",
                "source_hunks": [
                    {
                        "hunk_id": "draw-row-translation-scale-split-h0",
                        "old_start": 2561,
                        "old_lines": ["row_offset = HSD_JObjGetTranslationY(jobj2);"],
                        "new_start": 2561,
                        "new_lines": [
                            "post_ceiling_row_delta = "
                            "HSD_JObjGetTranslationY(jobj2) - base;"
                        ],
                    }
                ],
            },
        ],
        "retained_scored_probes": [
            {
                "candidate_id": source_family_ids[2],
                "source_retained": "build/probes/draw-digit-callarg-fsubs-temp.c",
                "source_hunks": [
                    {
                        "hunk_id": "draw-digit-callarg-fsubs-temp-h0",
                        "old_start": 2575,
                        "old_lines": ["HSD_JObjReqAnimAll(jobj, base);"],
                        "new_start": 2575,
                        "new_lines": [
                            "post_ceiling_digit_arg = (f32) digit;",
                            "HSD_JObjReqAnimAll(jobj, post_ceiling_digit_arg);",
                        ],
                    }
                ],
                "expression_score": {"matched": 0, "targeted": 3},
                "target_score": {"matched": 0, "targeted": 3},
            }
        ],
        "missing_inputs": [
            {"input": "draw_expression_materializer", "reason": "fixture-omitted"}
        ],
        "exhausted_dimensions": dimensions,
    }
    return payload


def _post_ceiling_route_continuation(
    tmp_path: Path,
    *,
    function: str = "mnDiagram_SortNamesByKOs",
    class_id: int = 0,
    parent_force: dict[str, int] | None = None,
    route_specs: list[tuple[str, list[list[int]], dict[str, int]]] | None = None,
) -> dict:
    parent_force = parent_force or _sort_force()
    route_specs = route_specs or [
        ("post-ceiling-sort-init-pointer-walk", [[34, 44]], _sort_force()),
        ("post-ceiling-sort-swap-materialization", [[34, 44]], _sort_force()),
    ]
    ranked = []
    for candidate_id, target_orders, candidate_force in route_specs:
        source_file = tmp_path / f"{candidate_id}.c"
        pcdump = tmp_path / f"{candidate_id}.pcdump.txt"
        command = (
            "melee-agent debug select-order-search "
            f"-f {function} --class {class_id} "
            f"--target 'r{target_orders[0][0]}<r{target_orders[0][1]}' "
            f"--pcdump {pcdump} --source-file {source_file} "
            "--force-phys "
            + ",".join(
                f"{ig}:{phys}"
                for ig, phys in sorted(
                    candidate_force.items(),
                    key=lambda item: int(item[0]),
                )
            )
            + " --json"
        )
        ranked.append({
            "status": "source-actionable",
            "kind": "retained-source-select-order-repair",
            "candidate_id": candidate_id,
            "source_retained": str(source_file),
            "pcdump_path": str(pcdump),
            "candidate_force_phys": candidate_force,
            "continuation": {
                "route": "retained-source-select-order-repair",
                "kind": "retained-source-select-order-repair",
                "target_orders": target_orders,
                "command": command,
                "source_retained": str(source_file),
                "pcdump_path": str(pcdump),
            },
        })
    return {
        "function": function,
        "post_ceiling_continuation_summary": {
            "status": "source-actionable",
            "kind": "post-ceiling-baseline-escape-continuation",
            "family_id": "post-ceiling-baseline-escape-continuation",
            "suppression_family": "post-ceiling-baseline-escape-continuation",
            "class_id": class_id,
            "final_force_phys": parent_force,
            "ranked_candidates": ranked,
            "blockers": [],
        },
    }


def _post_ceiling_select_order_terminal(
    tmp_path: Path,
    *,
    function: str = "mnDiagram_SortNamesByKOs",
    class_id: int = 0,
    candidate_id: str = "post-ceiling-sort-init-pointer-walk",
    target_orders: list[list[int]] | None = None,
    force: dict[str, int] | None = None,
    kind: str = "select-order-source-exhaustion",
    terminal_blocker: str = "transform-family-exhausted",
    pcdump_suffix: str = ".pcdump.txt",
) -> dict:
    target_orders = target_orders or [[34, 44]]
    force = force or _sort_force()
    return {
        "function": function,
        "status": "ok",
        "class_id": class_id,
        "target_orders": target_orders,
        "source": str(tmp_path / f"{candidate_id}.c"),
        "baseline_pcdump_path": str(tmp_path / f"{candidate_id}{pcdump_suffix}"),
        "terminal_exhaustion_summary": {
            "status": "blocked",
            "kind": kind,
            "dominant_blocker": "source-probes-exhausted",
            "terminal_blocker": terminal_blocker,
            "force_phys_targets": force,
            "blocker_targets": [target_orders[0][1]],
            "diagnostic_bucket_counts": {
                "force-phys-hit-target": 0,
                "force-phys-hit-protected": 0,
                "force-phys-hit-all": 0,
            },
        },
    }


def test_node_set_select_order_handoff_is_actionable_before_terminal(
    tmp_path: Path,
) -> None:
    handoff = _write_json(
        tmp_path / "draw" / "node_set_split_resumed.json",
        _draw_node_set_select_order_handoff(tmp_path),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[handoff],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["family_id"] == "retained-source-select-order-repair"
    assert next_frontier["actionable"] is True
    assert next_frontier["continuation"]["route"] == "command-hint"
    assert "debug select-order-search" in next_frontier["continuation"]["command"]
    assert next_frontier["attempted_targets"] == {"37": 26}
    assert next_frontier["protected_targets"] == {"32": 28, "46": 26}
    assert next_frontier["continuation"] is not None


def test_select_order_terminal_exhaustion_closes_node_set_handoff_route(
    tmp_path: Path,
) -> None:
    handoff = _write_json(
        tmp_path / "draw" / "node_set_split_resumed.json",
        _draw_node_set_select_order_handoff(tmp_path),
    )
    terminal = _write_json(
        tmp_path / "draw" / "select_order.json",
        _draw_select_order_case_c_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[handoff, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    assert fn["next_frontier"] is None
    assert fn["summary"]["unexhausted_count"] == 0
    assert fn["summary"]["terminal_count"] == 1
    assert fn["summary"]["suppressed_by_terminal_count"] == 1
    frontier = fn["terminal_frontiers"][0]
    assert frontier["terminal"] is True
    assert frontier["suppressed_by_terminal"] is True
    assert frontier["terminal_reason"] == "transform-family-exhausted"
    assert str(terminal) in frontier["closed_by"]
    assert frontier["attempted_targets"] == {"37": 26}
    assert frontier["protected_targets"] == {"32": 28, "46": 26}

    reversed_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[terminal, handoff],
    )
    reversed_fn = reversed_payload["functions"][0]
    assert reversed_payload["status"] == "all-known-frontiers-exhausted"
    assert reversed_fn["frontiers"] == []
    assert reversed_fn["summary"]["suppressed_by_terminal_count"] == 1


def test_post_ceiling_continuation_actionable_is_separate_frontier(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "continuation.json",
        _post_ceiling_continuation_actionable(tmp_path),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["family_id"] == "post-ceiling-baseline-escape-continuation"
    assert next_frontier["suppression_family"] == (
        "post-ceiling-baseline-escape-continuation"
    )
    assert "debug select-order-search" in next_frontier["continuation"]["command"]


def test_post_ceiling_continuation_terminal_does_not_merge_with_baseline_terminal(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "baseline_and_continuation.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "terminal_summary": {
                "status": "terminal",
                "kind": "no-post-ceiling-sort-source-family",
                "terminal_reason": (
                    "no-post-ceiling-sort-source-family/"
                    "current-source-shape-ceiling"
                ),
                "final_force_phys": _sort_force(),
            },
            **_post_ceiling_continuation_terminal(),
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    terminal_families = {
        frontier["family_id"]
        for frontier in payload["functions"][0]["terminal_frontiers"]
    }
    assert "post-ceiling-baseline-escape" in terminal_families
    assert "post-ceiling-baseline-escape-continuation" in terminal_families


def test_post_ceiling_source_model_terminal_proof_names_sort_levers(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "baseline_escape_full_closure.json",
        _sort_source_model_terminal_proof(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    proof = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    assert proof["terminal_reason"] == (
        "post-ceiling-gpr-case-c-source-model-ceiling"
    )
    source_model = proof["source_model_proof"]
    assert "pointer progression" in source_model["suspect_source_assumption"]
    assert "selected-slot" in source_model["suspect_source_assumption"]
    assert proof["attempted_targets"] == {"34": 27, "44": 25}
    assert {row["virtual"] for row in source_model["target_anchors"]} == {34, 44}
    assert {
        row["candidate_id"] for row in source_model["candidate_scores"]
    } == {
        "post-ceiling-sort-init-pointer-walk",
        "post-ceiling-sort-swap-materialization",
    }
    wrong_actuals = {
        row["candidate_id"]: {
            item["virtual"]: item["actual"]
            for item in row["wrong_registers"]
        }
        for row in source_model["candidate_scores"]
    }
    assert wrong_actuals["post-ceiling-sort-init-pointer-walk"] == {
        34: 24,
        44: 27,
    }
    assert wrong_actuals["post-ceiling-sort-swap-materialization"] == {
        34: 4,
        44: 31,
    }
    synthesis = source_model["source_family_synthesis"]
    assert synthesis["evidence_status"] == "fallback-inferred-from-local-candidates"
    assert synthesis["attempted_equivalence_classes"] == [
        "sort-init-indexed-write",
        "sort-swap-slot-lvalue",
    ]
    assert {
        row["dimension_id"] for row in synthesis["missing_dimensions"]
    } == {
        "sort-indexed-byte-cache",
        "sort-call-return-copy-local",
        "sort-protected-loss-init-lifetime",
    }
    assert "source-family discovery or plateau data" in (
        synthesis["next_unsupported_source_model"]
    )
    assert "transform-corpus adapter" in (
        source_model["next_unsupported_source_model"]
    )


def test_sort_source_model_fallback_does_not_infer_helper_context_from_free_text(
    tmp_path: Path,
) -> None:
    proof_payload = json.loads(json.dumps(_sort_source_model_terminal_proof()))
    proof_payload["candidates"][0]["strategy"] = "source-context audit only"
    proof_payload["candidates"][0]["rationale"] = (
        "Mention helper-data-layout and cross-function text without a generated "
        "post-meta source-context candidate."
    )
    proof_payload["score_classification"]["candidates"][0]["strategy"] = (
        "source-context audit only"
    )
    proof_payload["score_classification"]["candidates"][0]["rationale"] = (
        "Mention helper-data-layout and cross-function text without a generated "
        "post-meta source-context candidate."
    )
    artifact = _write_json(
        tmp_path / "sort" / "legacy_source_context_words.json",
        proof_payload,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    proof = next(
        frontier for frontier in payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    synthesis = proof["source_model_proof"]["source_family_synthesis"]
    helper_dimension = (
        "sort-helper-extraction-data-layout-or-cross-function-rewrite"
    )

    assert helper_dimension not in synthesis["attempted_equivalence_classes"]
    assert helper_dimension not in {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    }
    assert helper_dimension not in {
        row["dimension_id"] for row in synthesis["missing_dimensions"]
    }
    assert "source-family discovery or plateau data" in (
        synthesis["next_unsupported_source_model"]
    )


def test_post_ceiling_source_model_terminal_proof_enriches_extracted_sort_proof(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "baseline_escape_full_closure.json",
        _sort_source_model_terminal_proof(),
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )
    extracted_proof = next(
        frontier for frontier in first_payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    extracted_artifact = _write_json(
        tmp_path / "sort" / "source_model_terminal_proof.json",
        extracted_proof,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[extracted_artifact],
    )

    proof = next(
        frontier for frontier in payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    source_model = proof["source_model_proof"]
    synthesis = source_model["source_family_synthesis"]
    assert synthesis["evidence_status"] == "fallback-inferred-from-local-candidates"
    assert synthesis["attempted_equivalence_classes"] == [
        "sort-init-indexed-write",
        "sort-swap-slot-lvalue",
    ]
    assert "source-family discovery or plateau data" in (
        synthesis["next_unsupported_source_model"]
    )


def test_post_ceiling_source_model_terminal_proof_repairs_stale_sort_fpr_label(
    tmp_path: Path,
) -> None:
    seed_artifact = _write_json(
        tmp_path / "sort" / "baseline_escape_synthesis_closure.json",
        _sort_source_model_terminal_proof_with_synthesis(),
    )
    seed_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[seed_artifact],
    )
    stale_proof = next(
        frontier for frontier in seed_payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    source_model = stale_proof["source_model_proof"]
    stale_proof["terminal_reason"] = "post-ceiling-fpr-expression-source-model-ceiling"
    source_model["summary"] = (
        "mnDiagram_SortNamesByKOs reached a post-ceiling FPR expression "
        "source-model ceiling"
    )
    source_model["register_class"] = "fpr"
    source_model["expression_anchors"] = [
        {
            "virtual": 34,
            "name": "ig34",
            "expression": "sort gpr source span",
        }
    ]
    source_model["source_family_synthesis"]["evidence_status"] = (
        "fallback-inferred-from-local-candidates"
    )
    artifact = _write_json(
        tmp_path / "sort" / "stale_source_model_terminal_proof.json",
        stale_proof,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    proof = next(
        frontier for frontier in payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    source_model = proof["source_model_proof"]
    rows = {
        row["candidate_id"]: row for row in source_model["candidate_scores"]
    }
    row = rows["post-ceiling-source-family-sort-call-return-copy-local"]
    assert proof["terminal_reason"] == (
        "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
    )
    assert source_model["register_class"] == "gpr"
    assert source_model["expression_anchors"] == []
    assert "FPR expression" not in source_model["summary"]
    assert row["terminal_classification"] == "false-positive-target-progress"
    assert row["terminal_reason"] == "false-positive-virtual-id-hit"


def test_post_ceiling_source_model_terminal_proof_preserves_sort_synthesis_data(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "baseline_escape_synthesis_closure.json",
        _sort_source_model_terminal_proof_with_synthesis(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    proof = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    assert proof["terminal_reason"] == (
        "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
    )
    assert proof["kind"] == (
        "post-ceiling-gpr-case-c-source-model-synthesis-proof"
    )
    assert proof["attempted_targets"] == {"34": 27, "44": 25}
    assert proof["metrics"]["candidate_count"] > 2

    source_model = proof["source_model_proof"]
    assert source_model["register_class"] == "gpr"
    assert "FPR expression" not in source_model["summary"]
    by_candidate = {
        row["candidate_id"]: row for row in source_model["candidate_scores"]
    }
    call_return = by_candidate[
        "post-ceiling-source-family-sort-call-return-copy-local"
    ]
    assert call_return["classification"] == "target-progress"
    assert call_return["source_retained"] == (
        "build/probes/sort-call-return-copy-local.c"
    )
    assert call_return["pcdump_path"] == (
        "build/probes/sort-call-return-copy-local.pcdump.txt"
    )
    assert call_return["terminal_classification"] == (
        "false-positive-target-progress"
    )
    assert call_return["terminal_reason"] == "false-positive-virtual-id-hit"
    indexed_byte = by_candidate[
        "post-ceiling-source-family-sort-indexed-byte-cache"
    ]
    assert indexed_byte["source_retained"] == (
        "build/probes/sort-indexed-byte-cache.c"
    )
    assert indexed_byte["terminal_classification"] == (
        "false-positive-target-progress"
    )
    synthesis = source_model["source_family_synthesis"]
    assert synthesis["evidence_status"] == "artifact-synthesis-data"
    assert synthesis["forced_target_map"] == {"34": 27, "44": 25}
    assert set(synthesis["attempted_equivalence_classes"]) >= {
        "sort-init-indexed-write",
        "sort-indexed-byte-cache",
        "sort-call-return-copy-local",
        "sort-swap-slot-lvalue",
    }
    assert set(synthesis["generated_candidate_ids"]) == {
        "post-ceiling-source-family-sort-init-indexed-write",
        "post-ceiling-source-family-sort-indexed-byte-cache",
    }
    assert set(synthesis["scored_candidate_ids"]) >= {
        "post-ceiling-source-family-sort-init-indexed-write",
        "post-ceiling-source-family-sort-indexed-byte-cache",
        "post-ceiling-source-family-sort-call-return-copy-local",
        "post-ceiling-source-family-sort-swap-slot-lvalue",
    }
    assert set(synthesis["all_candidate_ids"]) >= {
        "post-ceiling-sort-init-pointer-walk",
        "post-ceiling-sort-swap-materialization",
        "post-ceiling-source-family-sort-init-indexed-write",
        "post-ceiling-source-family-sort-indexed-byte-cache",
        "post-ceiling-source-family-sort-call-return-copy-local",
        "post-ceiling-source-family-sort-swap-slot-lvalue",
    }
    assert synthesis["candidate_count"] > 2
    assert synthesis["source_hunks_by_candidate"][0]["source_hunks"][0][
        "hunk_id"
    ] == "sort-init-indexed-write-h0"
    assert synthesis["retained_scored_probes"][0]["candidate_id"] == (
        "post-ceiling-source-family-sort-call-return-copy-local"
    )
    assert synthesis["missing_inputs"] == [
        {"input": "pcdump_path", "reason": "fixture-omitted"}
    ]
    assert synthesis["skipped_dimensions"] == [
        {
            "dimension_id": "sort-transform-corpus-adapter",
            "reason": "not-owned-by-this-issue",
        }
    ]
    assert {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    } >= {
        "sort-init-indexed-write",
        "sort-indexed-byte-cache",
        "sort-call-return-copy-local",
        "sort-swap-slot-lvalue",
    }
    assert synthesis["next_unsupported_source_model"] == (
        "fixture: full transform-corpus adapter remains the next "
        "unsupported Sort source model"
    )
    assert source_model["next_unsupported_source_model"] == (
        synthesis["next_unsupported_source_model"]
    )


def test_retained_frontiers_meta_ceiling_groups_sort_terminal_roots(
    tmp_path: Path,
) -> None:
    artifacts = [
        _write_json(tmp_path / "sort" / "baseline.json", _sort_post_ceiling_terminal()),
        _write_json(tmp_path / "sort" / "inline.json", _sort_inline_boundary_terminal()),
        _write_json(
            tmp_path / "sort" / "source_model.json",
            _sort_source_model_terminal_proof_with_synthesis(),
        ),
        _write_json(
            tmp_path / "sort" / "addi.json",
            {
                "function": "mnDiagram_SortNamesByKOs",
                "kind": "target-only-backprojection-addi-copy-product-source-resolver",
                "status": "terminal",
                "terminal_reason": "addi-copy-product-operands-not-source-visible",
                "source_lever": "addi r3,r4,8",
                "attempted_targets": {"34": 27},
                "protected_targets": {"44": 25},
                "final_force_phys": _sort_force(),
            },
        ),
    ]

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=artifacts,
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    meta = fn["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["ranked_next_lanes"] == []
    assert meta["summary"]["unexhausted_count"] == 0
    group_families = {group["family_id"] for group in meta["terminal_groups"]}
    assert {
        "post-ceiling-source-model-proof",
        "inline-leverage-helper-boundary-continuation",
        "post-ceiling-baseline-escape",
        "target-only-backprojection-addi-copy-product",
    } <= group_families
    facts = {
        (fact["virtual"], fact["expected"], fact["actual"])
        for fact in meta["terminal_proof"]["allocator_facts"]
    }
    assert (34, 27, 24) in facts
    assert (44, 25, 27) in facts
    source_group = next(
        group for group in meta["terminal_groups"]
        if group["family_id"] == "post-ceiling-source-model-proof"
    )
    assert source_group["representative_frontiers"]
    assert "source_model_proof" not in source_group["representative_frontiers"][0]


def test_retained_frontiers_meta_ceiling_groups_draw_source_spans(
    tmp_path: Path,
) -> None:
    artifacts = [
        _write_json(
            tmp_path / "draw" / "source_model.json",
            _draw_source_model_terminal_proof_with_synthesis(),
        ),
        _write_json(
            tmp_path / "draw" / "sticky.json",
            {
                "function": "mnDiagram_DrawCellNumber",
                "kind": "target-only-c2-sticky-pool-source-attribution",
                "status": "terminal",
                "complete": True,
                "terminal_reason": (
                    "target-only-c2-sticky-pool-source-attribution-terminal"
                ),
                "source_lever": "col_offset",
                "attempted_targets": {"32": 28},
                "protected_targets": {"37": 26, "46": 26},
                "final_force_phys": {"32": 28, "37": 26, "46": 26},
            },
        ),
    ]

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=artifacts,
    )

    meta = payload["functions"][0]["meta_ceiling"]
    proof = meta["terminal_proof"]
    span_lines = {span.get("source_line") for span in proof["source_spans"]}
    assert {2561, 2564} <= span_lines
    group_families = {group["family_id"] for group in meta["terminal_groups"]}
    assert "target-only-c2-sticky-pool" in group_families
    assert "post-ceiling-source-model-proof" in group_families
    assert proof["next_unsupported_source_model"]


def test_retained_frontiers_meta_ceiling_preserves_actionable_lane_when_present(
    tmp_path: Path,
) -> None:
    action = _write_json(
        tmp_path / "sort" / "continuation.json",
        _post_ceiling_continuation_actionable(tmp_path),
    )
    terminal = _write_json(
        tmp_path / "sort" / "baseline.json",
        _sort_post_ceiling_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[action, terminal],
    )

    assert payload["status"] == "actionable"
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "actionable"
    assert meta["ranked_next_lanes"][0]["frontier_id"] == (
        payload["next_frontier"]["frontier_id"]
    )
    assert meta["next_frontier"]["frontier_id"] == payload["next_frontier"]["frontier_id"]
    assert "terminal_proof" not in meta


def test_retained_frontiers_meta_ceiling_does_not_resurrect_stale_lane(
    tmp_path: Path,
) -> None:
    action = _write_json(
        tmp_path / "sort" / "continuation.json",
        _post_ceiling_continuation_actionable(tmp_path),
    )
    terminal = _write_json(
        tmp_path / "sort" / "continuation_terminal.json",
        _post_ceiling_continuation_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[action, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["ranked_next_lanes"] == []
    assert meta["next_frontier"] is None


def test_retained_frontiers_meta_ceiling_does_not_promote_non_actionable_command_lane() -> None:
    stale_lane = {
        "frontier_id": (
            "mnDiagram_SortNamesByKOs|retained-source-select-order-repair|"
            "stale-score-source"
        ),
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "retained-source-select-order-repair",
        "kind": "retained-source-select-order-repair",
        "status": "source-actionable",
        "terminal": False,
        "actionable": False,
        "attempted_targets": {},
        "protected_targets": {},
        "final_force_phys": {},
        "continuation": {
            "route": "score-source",
            "source_retained": "build/diagnostics/sort/post-ceiling.c",
            "command": (
                "melee-agent debug target score-source "
                "build/diagnostics/sort/post-ceiling.c "
                "--function mnDiagram_SortNamesByKOs --json --retain-pcdump"
            ),
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [stale_lane],
                    "terminal_frontiers": [_sort_concrete_protected_loss_terminal()],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 1, "terminal_count": 1},
                }
            ],
            "next_frontier": None,
        },
        function="mnDiagram_SortNamesByKOs",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []
    assert "terminal_proof" in meta


def test_retained_frontiers_text_prints_meta_ceiling_summary(
    tmp_path: Path,
) -> None:
    source_model = _sort_source_model_terminal_proof_with_synthesis()
    source_model["post_ceiling_source_family_discovery"][
        "next_unsupported_source_family"
    ] = "sort-helper-extraction-data-layout-or-cross-function-rewrite"
    source_model["post_ceiling_source_family_discovery"][
        "next_unsupported_source_spans"
    ] = [
        {
            "candidate_id": "post-meta-sort-source-context-comparison-helper",
            "dimension_id": (
                "sort-helper-extraction-data-layout-or-cross-function-rewrite"
            ),
            "source_components": [
                {"component_id": "sort-helper-extraction"},
                {"component_id": "sort-cross-function-source-context"},
            ],
            "source_hunks": [{"hunk_id": "helper-h0"}],
        }
    ]
    artifact = _write_json(
        tmp_path / "sort" / "source_model.json",
        source_model,
    )
    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    text = render_retained_frontier_text(payload)

    assert "ceiling:" in text
    assert "post-ceiling-source-model-proof" in text
    assert "next unsupported source family: " in text
    assert "sort-helper-extraction-data-layout-or-cross-function-rewrite" in text
    assert "post-meta-sort-source-context-comparison-helper" in text
    assert "ig34 wants r27 got r24" in text


def test_post_ceiling_source_model_terminal_proof_names_draw_expression_spans(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "draw" / "baseline_escape_full_closure.json",
        _draw_source_model_terminal_proof(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    proof = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    assert proof["kind"] == "post-ceiling-fpr-expression-source-model-proof"
    assert proof["terminal_reason"] == (
        "post-ceiling-fpr-expression-source-model-ceiling"
    )
    source_model = proof["source_model_proof"]
    assert source_model["register_class"] == "fpr"
    assert "FPR expression source-model ceiling" in source_model["summary"]
    assert "row/column offset expressions" in (
        source_model["suspect_source_assumption"]
    )
    assert "digit-animation" in source_model["suspect_source_assumption"]
    assert proof["attempted_targets"] == {"32": 28, "37": 26, "46": 26}

    expression_by_virtual = {
        row["virtual"]: row for row in source_model["expression_anchors"]
    }
    assert expression_by_virtual[32]["name"] == "col_offset"
    assert expression_by_virtual[32]["expression"] == "y_spacing * (f32) col"
    assert expression_by_virtual[32]["baseline_source"]["source_line"] == 2564
    assert expression_by_virtual[37]["name"] == "row_offset"
    assert expression_by_virtual[46]["expression"] == "fsubs f46,f45,f44"

    candidate = source_model["candidate_scores"][0]
    assert candidate["candidate_id"] == "post-ceiling-digit-anim-callarg-block"
    assert candidate["expression_score"]["register_class"] == "fpr"
    assert candidate["target_score"]["targeted"] == 3
    expression_actuals = {
        row["virtual"]: row["actual"]
        for row in candidate["expression_wrong_registers"]
    }
    target_actuals = {
        row["virtual"]: row["actual"]
        for row in candidate["wrong_registers"]
    }
    assert expression_actuals == {32: 26, 37: 28, 46: 1}
    assert target_actuals == {32: 1, 37: 28, 46: 1}
    synthesis = source_model["source_family_synthesis"]
    assert synthesis["evidence_status"] == "fallback-inferred-from-local-candidates"
    assert synthesis["attempted_equivalence_classes"] == [
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
    ]
    assert {
        row["dimension_id"] for row in synthesis["missing_dimensions"]
    } == {
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
        DRAW_POST_SOURCE_CONTEXT_DIMENSION,
    }
    assert "Draw FPR expression source-family synthesis" in (
        synthesis["next_unsupported_source_model"]
    )
    assert source_model["next_unsupported_source_model"] == (
        synthesis["next_unsupported_source_model"]
    )


def test_retained_frontiers_prefers_draw_post_source_context_terminal_over_stale_handoff(
    tmp_path: Path,
) -> None:
    retained_row = {
        "candidate_id": (
            "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
        ),
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "target_score": {"matched": 1, "targeted": 3},
        "expression_score": {"matched": 1, "targeted": 3},
        "structural_guard": {
            "accepted": False,
            "reason": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 11,
            "opcode_similarity": 0.955684,
        },
        "source_hunks": [{"variant_id": "joint-data-owner-with-loop-object"}],
        "pcdump_path": "build/draw/post-whole.pcdump.txt",
    }
    artifact = _write_json(
        tmp_path / "draw" / "post_whole_terminal_frontiers.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "status": "all-known-frontiers-exhausted",
            "terminal_frontiers": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "terminal": True,
                    "family_id": "post-source-context-fpr-ceiling-next-dimension",
                    "source_model_proof": {
                        "kind": "post-source-context-fpr-next-dimension-discovery",
                        "status": "complete",
                        "next_unsupported_source_dimension": (
                            DRAW_POST_SOURCE_CONTEXT_DIMENSION
                        ),
                        "next_unsupported_source_family": "stale-family",
                        "next_unsupported_source_model": "stale-model",
                    },
                },
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "terminal": True,
                    "family_id": "post-source-context-fpr-ceiling-next-dimension",
                    "source_model_proof": {
                        "kind": "post-source-context-fpr-next-dimension-discovery",
                        "status": "complete",
                        "terminal_reason": (
                            "post-source-context-next-dimension/"
                            "unsupported-source-family"
                        ),
                        "exhausted_source_dimension": (
                            DRAW_POST_SOURCE_CONTEXT_DIMENSION
                        ),
                        "exhausted_dimensions": [
                            DRAW_POST_SOURCE_CONTEXT_DIMENSION
                        ],
                        "next_unsupported_source_dimension": (
                            DRAW_POST_SOURCE_CONTEXT_DIMENSION
                        ),
                        "next_unsupported_source_family": (
                            DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
                        ),
                        "next_unsupported_source_model": (
                            DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
                        ),
                        "candidate_scores": [retained_row],
                        "retained_scored_probes": [retained_row],
                    },
                },
            ],
            "next_frontier": None,
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
    )
    assert proof.get("next_unsupported_source_dimension") != (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert proof["candidate_scores"][0]["candidate_id"] == (
        "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
    )


def test_retained_frontiers_draw_post_all_known_actionable_outranks_stale_handoff() -> None:
    stale_lane = {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-stale-post-source-context",
        "family_id": "post-source-context-fpr-ceiling-next-dimension",
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "status": "source-actionable",
        "terminal": False,
        "rank": 1,
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "continuation": {
            "route": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            "source_hunks": [{"hunk_id": "stale-handoff"}],
        },
    }
    post_all_known_lane = {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-post-all-known-candidate",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "terminal": False,
        "rank": 99,
        "dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION,
        "source_model_proof": {
            "attempted_equivalence_classes": [DRAW_POST_ALL_KNOWN_DIMENSION],
            "source_family_synthesis": {
                "evidence_status": "artifact-score-rows",
                "exhausted_dimensions": [
                    {"dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION}
                ],
            },
        },
        "continuation": {
            "route": DRAW_POST_ALL_KNOWN_DIMENSION,
            "candidate_id": "draw-post-all-known-candidate",
            "source_hunks": [{"hunk_id": "post-all-known"}],
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "actionable",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [stale_lane, post_all_known_lane],
                    "terminal_frontiers": [],
                    "next_frontier": stale_lane,
                    "summary": {"unexhausted_count": 2, "terminal_count": 0},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    assert meta["next_frontier"]["frontier_id"] == "draw-post-all-known-candidate"
    assert meta["next_frontier"]["continuation"]["route"] == (
        DRAW_POST_ALL_KNOWN_DIMENSION
    )


def test_retained_frontiers_draw_post_all_known_terminal_suppresses_stale_handoff() -> None:
    stale_lane = {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-stale-post-source-context",
        "family_id": "post-source-context-fpr-ceiling-next-dimension",
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "status": "source-actionable",
        "terminal": False,
        "rank": 1,
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "continuation": {
            "route": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            "source_hunks": [{"hunk_id": "stale-handoff"}],
        },
    }
    stale_terminal = _draw_source_model_terminal(
        dimension_id=DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        next_model=DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
        next_family=DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
    )
    post_all_known_terminal = _draw_source_model_terminal(
        dimension_id=DRAW_POST_ALL_KNOWN_DIMENSION,
        next_model=DRAW_POST_ALL_KNOWN_FINAL_MODEL,
        next_family=DRAW_POST_ALL_KNOWN_FINAL_FAMILY,
    )
    payload = {
        "status": "all-known-frontiers-exhausted",
        "artifact_count": 1,
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": [stale_lane],
                "terminal_frontiers": [
                    stale_terminal,
                    post_all_known_terminal,
                ],
                "next_frontier": None,
                "summary": {"unexhausted_count": 1, "terminal_count": 2},
            }
        ],
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        payload,
        function="mnDiagram_DrawCellNumber",
    )
    payload["functions"][0]["meta_ceiling"] = meta
    text = render_retained_frontier_text(payload)

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_ALL_KNOWN_FINAL_FAMILY
    )
    assert proof["next_unsupported_source_model"] == DRAW_POST_ALL_KNOWN_FINAL_MODEL
    assert DRAW_POST_ALL_KNOWN_DIMENSION in {
        row["dimension_id"]
        for row in proof["source_family_synthesis"]["exhausted_dimensions"]
    }
    assert DRAW_POST_ALL_KNOWN_FINAL_FAMILY in text
    assert "draw-stale-post-source-context" not in text


def _draw_stack_clean_no_anchor_evidence() -> dict:
    return {
        "kind": "draw-product-translate-stack-clean-no-anchor-evidence",
        "status": "repair-handoff",
        "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "source_dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION,
        "seed_candidate_id": (
            "draw-post-all-known-product-translate-graph-"
            "col-product-before-row-delta-with-y-offset"
        ),
        "source_retained": "build/stack-clean-seed.c",
        "pcdump_path": "build/stack-clean-seed.pcdump.txt",
        "source_hunks": [{"hunk_id": "stack-clean-seed"}],
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26},
                "37": {"expected": 26, "actual": 28},
                "46": {"expected": 26, "actual": 2},
            },
        },
        "expression_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26},
                "37": {"expected": 26, "actual": 28},
                "46": {"expected": 26, "actual": 2},
            },
        },
        "stack_frame_facts": {
            "classification": "stack-layout",
            "expected_frame": 168,
            "current_frame": 176,
            "frame_delta": 8,
            "normalized_diff_lines": 0,
            "opcode_similarity": 1.0,
        },
        "target_virtual_facts": [
            {"virtual": 32, "expected": 28, "actual": 26, "matched": False},
            {"virtual": 37, "expected": 26, "actual": 28, "matched": False},
            {"virtual": 46, "expected": 26, "actual": 2, "matched": False},
        ],
        "expression_virtual_facts": [
            {"virtual": 32, "expected": 28, "actual": 26, "matched": False},
            {"virtual": 37, "expected": 26, "actual": 28, "matched": False},
            {"virtual": 46, "expected": 26, "actual": 2, "matched": False},
        ],
        "ranked_recovery_probes": [
            {"probe_id": "row-delta-anchor-local", "rank": 1},
            {"probe_id": "digit-fsubs-anchor-temp", "rank": 2},
        ],
    }


def _draw_product_translate_terminal_with_stack_clean_evidence() -> dict:
    terminal = _draw_source_model_terminal(
        dimension_id=DRAW_PRODUCT_TRANSLATE_DIMENSION,
        next_model=(
            "Draw post-product/translate stack-clean/no-anchor recovery from "
            "an opcode-clean product/translate seed with stack-frame drift "
            "and missing IG32/IG37/IG46 expression anchors."
        ),
        next_family=DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
    )
    evidence = _draw_stack_clean_no_anchor_evidence()
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    for target in (proof, synthesis):
        target["next_unsupported_source_dimension"] = (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
        target["stack_clean_no_anchor_evidence"] = evidence
    terminal["stack_clean_no_anchor_evidence"] = evidence
    return terminal


def _draw_stack_clean_no_anchor_completed_terminal() -> dict:
    terminal = _draw_product_translate_terminal_with_stack_clean_evidence()
    terminal["terminal_reason"] = DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    proof["attempted_equivalence_classes"] = [
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    ]
    proof["terminal_reason"] = DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    proof["terminal_blockers"] = [
        {"reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER}
    ]
    proof["next_unsupported_source_family"] = (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    proof["next_unsupported_source_model"] = (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
    )
    synthesis["attempted_equivalence_classes"] = [
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    ]
    synthesis["exhausted_dimensions"] = [
        {
            "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
            ),
        }
    ]
    synthesis["terminal_blockers"] = proof["terminal_blockers"]
    synthesis["next_unsupported_source_family"] = (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    synthesis["next_unsupported_source_model"] = (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
    )
    return terminal


def _draw_post_stack_clean_no_anchor_source_shape_completed_terminal() -> dict:
    terminal = _draw_stack_clean_no_anchor_completed_terminal()
    retained = [
        {
            "candidate_id": (
                "draw-post-stack-clean-no-anchor-shape-digit-base-post-anim-temp"
            ),
            "target_score": {
                "matched": 0,
                "targeted": 3,
                "virtuals": {
                    "32": {"expected": 28, "actual": 26, "matched": False},
                    "37": {"expected": 26, "actual": None, "matched": False},
                    "46": {"expected": 26, "actual": 2, "matched": False},
                },
            },
            "expression_score": {
                "matched": 0,
                "targeted": 3,
                "virtuals": {
                    "32": {"expected": 28, "actual": 26, "matched": False},
                    "37": {"expected": 26, "actual": None, "matched": False},
                    "46": {"expected": 26, "actual": 2, "matched": False},
                },
            },
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 22,
                "rejection_reason": "signature-type-mismatch",
            },
            "source_retained": "build/draw/post-stack-digit-base.c",
            "pcdump_path": "build/draw/post-stack-digit-base.pcdump.txt",
        },
        {
            "candidate_id": (
                "draw-post-stack-clean-no-anchor-shape-row-delta-callsite-"
                "late-materialize"
            ),
            "target_score": {"matched": 0, "targeted": 3},
            "expression_score": {"matched": 0, "targeted": 3},
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 0,
                "expected_frame": 168,
                "current_frame": 184,
                "frame_delta": 16,
                "rejection_reason": "stack-layout",
            },
            "source_retained": "build/draw/post-stack-row-delta.c",
            "pcdump_path": "build/draw/post-stack-row-delta.pcdump.txt",
        },
        {
            "candidate_id": (
                "draw-post-stack-clean-no-anchor-shape-row-delta-two-step-"
                "owner-reuse"
            ),
            "target_score": {"matched": 0, "targeted": 3},
            "expression_score": {"matched": 0, "targeted": 3},
        },
    ]
    post_stack_evidence = {
        "ranked_post_stack_clean_probes": retained,
        "best_candidate_id": retained[0]["candidate_id"],
    }
    terminal.update(
        {
            "terminal_reason": (
                DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
            ),
            "terminal_blocker": (
                DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER
            ),
            "post_stack_clean_no_anchor_evidence": post_stack_evidence,
        }
    )
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    for target in (proof, synthesis):
        target["attempted_equivalence_classes"] = [
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        ]
        target["exhausted_dimensions"] = [
            {
                "dimension_id": (
                    DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
                ),
                "status": "scored-terminal",
                "exhaustion_reason": (
                    DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
                ),
            }
        ]
        target["terminal_reason"] = (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
        )
        target["terminal_blocker"] = (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER
        )
        target["next_unsupported_source_family"] = (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
        )
        target["post_stack_clean_no_anchor_evidence"] = post_stack_evidence
        target["retained_scored_probes"] = retained
        target["candidate_scores"] = retained
    proof["next_unsupported_source_dimension"] = None
    synthesis["next_unsupported_source_dimension"] = None
    return terminal


def _draw_post_stack_loop_callsite_source_context_completed_terminal() -> dict:
    terminal = _draw_post_stack_clean_no_anchor_source_shape_completed_terminal()
    retained = [
        {
            "candidate_id": "draw-post-stack-loop-callsite-loop-digit-jobj-owner",
            "target_score": {"matched": 0, "targeted": 3},
            "expression_score": {"matched": 0, "targeted": 3},
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 0,
                "expected_frame": 168,
                "current_frame": 184,
                "frame_delta": 16,
                "rejection_reason": "stack-layout",
            },
            "source_retained": "build/draw/post-stack-loop-digit-jobj-owner.c",
            "pcdump_path": "build/draw/post-stack-loop-digit-jobj-owner.pcdump.txt",
        }
    ]
    terminal.update(
        {
            "terminal_reason": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
            ),
            "terminal_blocker": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
            ),
        }
    )
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    for target in (proof, synthesis):
        target["attempted_equivalence_classes"] = [
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        ]
        target["exhausted_dimensions"] = [
            {
                "dimension_id": (
                    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
                ),
                "status": "scored-terminal",
                "exhaustion_reason": (
                    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
                ),
            }
        ]
        target["terminal_reason"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
        )
        target["terminal_blocker"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
        )
        target["next_unsupported_source_family"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
        )
        target["next_unsupported_source_dimension"] = None
        target["retained_scored_probes"] = retained
        target["candidate_scores"] = retained
    return terminal


def _draw_post_stack_loop_callsite_owner_split_completed_terminal() -> dict:
    terminal = _draw_post_stack_loop_callsite_source_context_completed_terminal()
    retained = [
        {
            "candidate_id": "draw-post-stack-loop-callsite-expression-anchor-owner-row-offset-owner-split",
            "dimension_id": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION
            ),
            "target_score": {"matched": 1, "targeted": 3},
            "expression_score": {"matched": 0, "targeted": 3},
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 0,
                "expected_frame": 168,
                "current_frame": 176,
                "frame_delta": 8,
                "rejection_reason": "stack-layout",
            },
            "stack_frame_facts": {
                "classification": "stack-layout",
                "expected_frame": 168,
                "current_frame": 176,
                "frame_delta": 8,
            },
            "source_retained": "build/draw/post-row-offset-owner-split.c",
            "pcdump_path": "build/draw/post-row-offset-owner-split.pcdump.txt",
            "source_hunks": [{"hunk_id": "post-row-offset-owner-split"}],
        }
    ]
    terminal.update(
        {
            "terminal_reason": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON
            ),
            "terminal_blocker": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_BLOCKER
            ),
        }
    )
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    exhausted = [
        {
            "dimension_id": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION
            ),
            "status": "scored-terminal",
            "exhaustion_reason": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON
            ),
        },
    ]
    for target in (proof, synthesis):
        target["attempted_equivalence_classes"] = [
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION,
        ]
        target["exhausted_dimensions"] = [dict(row) for row in exhausted]
        target["exhausted_source_dimension"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION
        )
        target["terminal_reason"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON
        )
        target["terminal_blocker"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_BLOCKER
        )
        target["next_unsupported_source_family"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_MODEL
        )
        target["retained_scored_probes"] = retained
        target["candidate_scores"] = retained
        target["source_hunks_by_candidate"] = [
            {
                "candidate_id": retained[0]["candidate_id"],
                "dimension_id": (
                    DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION
                ),
                "source_hunks": retained[0]["source_hunks"],
                "source_retained": retained[0]["source_retained"],
                "pcdump_path": retained[0]["pcdump_path"],
            }
        ]
    return terminal


def _draw_post_row_offset_owner_expression_lifetime_completed_terminal() -> dict:
    terminal = _draw_post_stack_loop_callsite_owner_split_completed_terminal()
    retained = [
        {
            "candidate_id": (
                "draw-post-row-offset-owner-expression-lifetime-"
                "row-offset-adj-callsite-owner"
            ),
            "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
            "target_score": {"matched": 1, "targeted": 3},
            "target_matched": 1,
            "target_targeted": 3,
            "expression_score": {"matched": 0, "targeted": 3},
            "expression_matched": 0,
            "expression_targeted": 3,
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 0,
                "expected_frame": 168,
                "current_frame": 176,
                "frame_delta": 8,
                "rejection_reason": "stack-layout",
            },
            "stack_frame_facts": {
                "classification": "stack-layout",
                "expected_frame": 168,
                "current_frame": 176,
                "frame_delta": 8,
            },
            "source_retained": "build/draw/post-row-offset-lifetime.c",
            "pcdump_path": "build/draw/post-row-offset-lifetime.pcdump.txt",
            "source_hunks": [{"hunk_id": "post-row-offset-lifetime"}],
        }
    ]
    evidence = {
        "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
        "ranked_post_row_offset_owner_expression_lifetime_seeds": [
            {
                "candidate_id": (
                    "draw-post-stack-loop-callsite-expression-anchor-owner-"
                    "row-offset-owner-split"
                ),
                "source_retained": "build/draw/post-row-offset-owner-split.c",
                "pcdump_path": "build/draw/post-row-offset-owner-split.pcdump.txt",
                "source_hunks": [{"hunk_id": "post-row-offset-owner-split"}],
                "stack_frame_facts": {"frame_delta": 8},
            }
        ],
        "candidate_scores": retained,
        "retained_scored_probes": retained,
        "source_hunks_by_candidate": [
            {
                "candidate_id": retained[0]["candidate_id"],
                "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
                "source_hunks": retained[0]["source_hunks"],
                "source_retained": retained[0]["source_retained"],
                "pcdump_path": retained[0]["pcdump_path"],
            }
        ],
        "source_retained": "build/draw/post-row-offset-owner-split.c",
        "pcdump_path": "build/draw/post-row-offset-owner-split.pcdump.txt",
        "source_hunks": [{"hunk_id": "post-row-offset-owner-split"}],
    }
    terminal.update(
        {
            "terminal_reason": (
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
            ),
            "terminal_blocker": (
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER
            ),
            "post_row_offset_owner_expression_lifetime_evidence": evidence,
        }
    )
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    exhausted = [
        {
            "dimension_id": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION
            ),
            "status": "scored-terminal",
            "exhaustion_reason": (
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON
            ),
        },
        {
            "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": (
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
            ),
        },
    ]
    for target in (proof, synthesis):
        target["attempted_equivalence_classes"] = [
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION,
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
        ]
        target["exhausted_dimensions"] = [dict(row) for row in exhausted]
        target["exhausted_source_dimension"] = (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        )
        target["terminal_reason"] = (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
        )
        target["terminal_blocker"] = (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER
        )
        target["next_unsupported_source_family"] = (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL
        )
        target["retained_scored_probes"] = retained
        target["candidate_scores"] = retained
        target["source_hunks_by_candidate"] = evidence["source_hunks_by_candidate"]
        target["post_row_offset_owner_expression_lifetime_evidence"] = evidence
    return terminal


def _draw_stack_clean_no_anchor_terminal_summary_only() -> dict:
    terminal = _draw_product_translate_terminal_with_stack_clean_evidence()
    evidence = _draw_stack_clean_no_anchor_evidence()
    seed = evidence["seed_candidate_id"]
    terminal["terminal"] = True
    terminal["suppression_family"] = "post-ceiling-baseline-escape"
    terminal["terminal_summary"] = {
        "status": "terminal",
        "kind": "no-post-ceiling-draw-source-family",
        "family_id": "post-ceiling-baseline-escape",
        "suppression_family": "post-ceiling-baseline-escape",
        "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
        "terminal_blockers": [
            {"reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER}
        ],
        "next_unsupported_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "next_unsupported_source_family": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        ),
        "exhausted_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "suppressed_frontier_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "suppressed_candidate_id": seed,
        "stack_clean_no_anchor_evidence": evidence,
        "exhausted_dimensions": [
            {
                "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
                "status": "scored-terminal",
                "exhaustion_reason": (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
                ),
            }
        ],
        "candidate_count": 0,
        "scored_count": 0,
        "best_target_matched": 0,
        "best_target_targeted": 3,
    }
    return terminal


def _draw_helper_boundary_retained_candidate() -> dict:
    return {
        "candidate_id": (
            "draw-post-product-translate-stack-clean-continuation-"
            "col-product-row-digit-fpr-lifetime"
        ),
        "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "source_retained": "build/draw/helper-boundary-seed.c",
        "pcdump_path": "build/draw/helper-boundary-seed.pcdump.txt",
        "source_hunks": [{"hunk_id": "helper-boundary-seed"}],
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26},
                "37": {"expected": 26, "actual": 28},
                "46": {"expected": 26, "actual": 1},
            },
        },
        "expression_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26},
                "37": {"expected": 26, "actual": 28},
                "46": {"expected": 26, "actual": 1},
            },
        },
        "target_virtual_facts": [
            {"virtual": 32, "expected": 28, "actual": 26, "matched": False},
            {"virtual": 37, "expected": 26, "actual": 28, "matched": False},
            {"virtual": 46, "expected": 26, "actual": 1, "matched": False},
        ],
        "expression_virtual_facts": [
            {"virtual": 32, "expected": 28, "actual": 26, "matched": False},
            {"virtual": 37, "expected": 26, "actual": 28, "matched": False},
            {"virtual": 46, "expected": 26, "actual": 1, "matched": False},
        ],
        "stack_frame_facts": {
            "classification": "stack-layout",
            "expected_frame": 168,
            "current_frame": 176,
            "frame_delta": 8,
        },
    }


def _draw_helper_boundary_terminal_continuation() -> dict:
    terminal = _draw_issue998_terminalized_continuation()
    candidate = _draw_helper_boundary_retained_candidate()
    terminal["ranked_retained_candidates"] = [candidate]
    terminal["source_retained"] = candidate["source_retained"]
    terminal["pcdump_path"] = candidate["pcdump_path"]
    terminal["source_hunks"] = candidate["source_hunks"]

    proof = terminal["source_model_proof"]
    proof["ranked_retained_candidates"] = [candidate]
    proof["next_unsupported_source_dimension"] = (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    synthesis = proof["source_family_synthesis"]
    attempted = list(synthesis["attempted_equivalence_classes"])
    if DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION not in attempted:
        attempted.append(DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION)
    synthesis["attempted_equivalence_classes"] = attempted
    synthesis["exhausted_dimensions"].append(
        {
            "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "status": "continuation-exhausted",
        }
    )
    synthesis["retained_scored_probes"] = [candidate]
    synthesis["next_unsupported_source_dimension"] = (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    synthesis["unsupported_source_expression_class"] = (
        DRAW_COUPLED_UNSUPPORTED_CLASS
    )
    return terminal


def _draw_helper_boundary_completed_terminal() -> dict:
    force = _draw_issue998_force()
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-helper-boundary-terminal",
        "family_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "suppression_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blocker": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "attempted_targets": force,
        "final_force_phys": force,
        "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        "exhausted_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_HELPER_BOUNDARY_FINAL_MODEL,
        "source_model_proof": {
            "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
            "exhausted_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
            "next_unsupported_source_model": DRAW_HELPER_BOUNDARY_FINAL_MODEL,
            "source_family_synthesis": {
                "status": "terminal",
                "attempted_equivalence_classes": [
                    DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
                ],
                "exhausted_dimensions": [
                    {
                        "dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
                        "exhaustion_reason": (
                            DRAW_HELPER_BOUNDARY_TERMINAL_REASON
                        ),
                    }
                ],
                "terminal_blockers": [
                    {"reason": DRAW_HELPER_BOUNDARY_TERMINAL_REASON}
                ],
            },
        },
    }


def _draw_helper_boundary_suggest_inlines_terminal_report() -> dict:
    candidate_ids = ["void-helper-0001", "void-helper-0002"]
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "terminal",
        "terminal_blocker": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blockers": [
            {
                "reason": DRAW_HELPER_BOUNDARY_REJECTION_REASON,
                "count": len(candidate_ids),
                "candidate_ids": candidate_ids,
            }
        ],
        "candidates": [
            {
                "candidate_id": candidate_id,
                "kind": "void-helper",
                "rejection_reason": DRAW_HELPER_BOUNDARY_REJECTION_REASON,
            }
            for candidate_id in candidate_ids
        ],
        "patches": [],
        "scores": [],
        "messages": [
            (
                "all inline/helper candidates were rejected; verification has "
                "no accepted patches to score"
            )
        ],
    }


def _draw_helper_boundary_suggest_inlines_retained_score_rows(
    *,
    expression_matched: int = 0,
) -> dict:
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "ok",
        "score_mode": "score-source",
        "score_rows": [
            {
                "candidate_id": "block-macro-0001",
                "family": "inline-local-write-helper",
                "transform_family": "local-write-helper",
                "dimension_id": "inline-local-write-helper-block-macro",
                "source_retained": "build/draw/block-macro-0001.c",
                "source_file": "build/draw/block-macro-0001.c",
                "pcdump_path": "build/draw/block-macro-0001.pcdump.txt",
                "target_matched": 1,
                "target_targeted": 3,
                "target_virtual_distance": 2,
                "target_score": {
                    "matched": 1,
                    "targeted": 3,
                    "virtual_distance": 2,
                    "virtuals": {
                        "32": {
                            "expected": 28,
                            "actual": 28,
                            "matched": True,
                        },
                        "37": {
                            "expected": 26,
                            "actual": 28,
                            "matched": False,
                        },
                        "46": {
                            "expected": 26,
                            "actual": 1,
                            "matched": False,
                        },
                    },
                },
                "expression_matched": expression_matched,
                "expression_targeted": 3,
                "expression_virtual_distance": 3 - expression_matched,
                "expression_score": {
                    "register_class": "fpr",
                    "matched": expression_matched,
                    "targeted": 3,
                    "virtual_distance": 3 - expression_matched,
                    "virtuals": {
                        "32": {
                            "expected": 28,
                            "actual": 26,
                            "matched": False,
                        },
                        "37": {
                            "expected": 26,
                            "actual": 28,
                            "matched": False,
                        },
                        "46": {
                            "expected": 26,
                            "actual": 1,
                            "matched": False,
                        },
                    },
                },
                "structural_guard": {
                    "accepted": True,
                    "classification_primary": "normalized-structural-match",
                    "normalized_diff_lines": 0,
                    "frame_delta": None,
                },
            },
            {
                "candidate_id": "scalar-return-helper-0001",
                "family": "inline-local-write-helper",
                "transform_family": "local-write-helper",
                "dimension_id": "inline-local-write-helper-scalar-return-helper",
                "source_retained": "build/draw/scalar-return-helper-0001.c",
                "source_file": "build/draw/scalar-return-helper-0001.c",
                "pcdump_path": "build/draw/scalar-return-helper-0001.pcdump.txt",
                "target_matched": 1,
                "target_targeted": 3,
                "target_score": {
                    "matched": 1,
                    "targeted": 3,
                    "virtuals": {
                        "32": {
                            "expected": 28,
                            "actual": 28,
                            "matched": True,
                        },
                        "37": {
                            "expected": 26,
                            "actual": 28,
                            "matched": False,
                        },
                        "46": {
                            "expected": 26,
                            "actual": 1,
                            "matched": False,
                        },
                    },
                },
                "expression_matched": 0,
                "expression_targeted": 3,
                "expression_score": {
                    "register_class": "fpr",
                    "matched": 0,
                    "targeted": 3,
                    "virtuals": {},
                },
                "structural_guard": {
                    "accepted": False,
                    "classification_primary": "stack-layout",
                    "normalized_diff_lines": 0,
                    "frame_delta": 8,
                    "rejection_reason": "checkdiff structural drift: stack-layout",
                },
                "blockers": [
                    {
                        "reason": "structural-guard:stack-layout",
                        "candidate_id": "scalar-return-helper-0001",
                    }
                ],
            },
        ],
    }


def _draw_helper_boundary_abstract_terminal_continuation() -> dict:
    terminal = _draw_helper_boundary_terminal_continuation()
    for key in ("source_retained", "pcdump_path", "source_hunks"):
        terminal.pop(key, None)
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    for rows in (
        terminal.get("ranked_retained_candidates") or [],
        proof.get("ranked_retained_candidates") or [],
        synthesis.get("retained_scored_probes") or [],
    ):
        for row in rows:
            for key in ("source_retained", "pcdump_path", "source_hunks"):
                row.pop(key, None)
    return terminal


def test_retained_frontiers_draw_product_translate_terminal_outranks_post_all_known() -> None:
    post_all_known_terminal = _draw_source_model_terminal(
        dimension_id=DRAW_POST_ALL_KNOWN_DIMENSION,
        next_model=DRAW_POST_ALL_KNOWN_FINAL_MODEL,
        next_family=DRAW_POST_ALL_KNOWN_FINAL_FAMILY,
    )
    product_translate_terminal = _draw_source_model_terminal(
        dimension_id=DRAW_PRODUCT_TRANSLATE_DIMENSION,
        next_model=DRAW_PRODUCT_TRANSLATE_FINAL_MODEL,
        next_family=DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY,
    )

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        post_all_known_terminal,
                        product_translate_terminal,
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    proof = meta["terminal_proof"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert proof["next_unsupported_source_family"] == (
        DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_PRODUCT_TRANSLATE_FINAL_MODEL
    )
    assert DRAW_PRODUCT_TRANSLATE_DIMENSION in {
        row["dimension_id"]
        for row in proof["source_family_synthesis"]["exhausted_dimensions"]
    }


def test_retained_frontiers_draw_product_translate_actionable_outranks_post_all_known() -> None:
    post_all_known_lane = {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-post-all-known-candidate",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-ceiling-source-model-proof",
        "status": "source-actionable",
        "actionable": True,
        "candidate_id": "draw-post-all-known-candidate",
        "dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION,
        "continuation": {
            "route": DRAW_POST_ALL_KNOWN_DIMENSION,
            "candidate_id": "draw-post-all-known-candidate",
            "source_hunks": [{"hunk_id": "post-all-known"}],
        },
    }
    product_translate_lane = {
        **post_all_known_lane,
        "frontier_id": "draw-product-translate-candidate",
        "candidate_id": "draw-post-all-known-product-translate-graph-candidate",
        "dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION,
        "continuation": {
            "route": DRAW_PRODUCT_TRANSLATE_DIMENSION,
            "candidate_id": "draw-post-all-known-product-translate-graph-candidate",
            "source_hunks": [{"hunk_id": "product-translate"}],
            "pcdump_path": "build/product-translate.pcdump.txt",
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "actionable",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [post_all_known_lane, product_translate_lane],
                    "terminal_frontiers": [],
                    "next_frontier": post_all_known_lane,
                    "summary": {"unexhausted_count": 2, "terminal_count": 0},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    assert meta["next_frontier"]["frontier_id"] == (
        "draw-product-translate-candidate"
    )
    assert meta["next_frontier"]["continuation"]["route"] == (
        DRAW_PRODUCT_TRANSLATE_DIMENSION
    )


def test_stack_clean_no_anchor_recovery_frontier_outranks_product_translate_terminal() -> None:
    post_all_known_terminal = _draw_source_model_terminal(
        dimension_id=DRAW_POST_ALL_KNOWN_DIMENSION,
        next_model=DRAW_POST_ALL_KNOWN_FINAL_MODEL,
        next_family=DRAW_POST_ALL_KNOWN_FINAL_FAMILY,
    )
    product_translate_terminal = (
        _draw_product_translate_terminal_with_stack_clean_evidence()
    )

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        post_all_known_terminal,
                        product_translate_terminal,
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    frontier = meta["next_frontier"]
    assert frontier["dimension_id"] == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    assert frontier["continuation"]["route"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert frontier["continuation"]["seed_candidate_id"] == (
        _draw_stack_clean_no_anchor_evidence()["seed_candidate_id"]
    )
    assert frontier["continuation"]["source_hunks"] == [
        {"hunk_id": "stack-clean-seed"}
    ]
    assert frontier["continuation"]["pcdump_path"] == (
        "build/stack-clean-seed.pcdump.txt"
    )
    assert frontier["continuation"]["target_score"]["matched"] == 0
    assert frontier["continuation"]["expression_score"]["matched"] == 0
    assert frontier["continuation"]["stack_frame_facts"]["frame_delta"] == 8


def _draw_protected_subhunk_terminal(*, include_evidence: bool = True) -> dict:
    source_hunks = [
        {
            "hunk_id": "draw-row-delta-parent",
            "old_start": 2561,
            "old_lines": [
                "if (row_offset > 0.0f) {",
                "    row_offset_adj = row_offset;",
                "}",
            ],
            "new_start": 2561,
            "new_lines": [
                "if (row_offset >= 0.0f) {",
                "    row_offset_adj = row_offset - 1.0f;",
                "}",
            ],
            "protected_subhunks": [
                {
                    "hunk_id": "draw-row-delta-parent-row-delta",
                    "old_start": 2562,
                    "old_lines": ["    row_offset_adj = row_offset;"],
                    "new_start": 2562,
                    "new_lines": ["    row_offset_adj = row_offset - 1.0f;"],
                    "source_expression": "row_offset_adj",
                    "target_virtuals": [37],
                }
            ],
        }
    ]
    row = {
        "candidate_id": (
            "post-meta-source-family-draw-row-translation-scale-split-"
            "row-delta-local"
        ),
        "dimension_id": "draw-row-translation-scale-split",
        "normalized_diff_lines": 0,
        "target_score": {
            "matched": 1,
            "targeted": 3,
            "virtual_distance": 2,
            "virtuals": {"37": {"expected": 26, "actual": 26, "matched": True}},
        },
        "expression_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "false_positive_virtual_id_hit_count": 1,
            "virtuals": {
                "37": {
                    "expected": 26,
                    "actual": None,
                    "matched": False,
                    "status": "missing-expression",
                }
            },
        },
    }
    if include_evidence:
        row.update({
            "source_retained": "build/draw-row-delta.c",
            "pcdump_path": "build/draw-row-delta.pcdump.txt",
            "source_hunks": source_hunks,
        })
    synthesis = {
        "status": "synthesis-exhausted",
        "evidence_status": "artifact-score-rows",
        "attempted_equivalence_classes": ["draw-row-translation-scale-split"],
        "all_candidate_ids": [row["candidate_id"]],
        "candidate_count": 1,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "source_hunks_by_candidate": [
            {
                "candidate_id": row["candidate_id"],
                "dimension_id": row["dimension_id"],
                "source_hunks": source_hunks if include_evidence else [],
            }
        ],
        "terminal_blockers": [
            "manual-subhunk-range-required",
            "all-recombines-lost-protected-anchors",
            "expression-frontier-anchor-not-retained",
        ],
        "next_unsupported_source_model": "fixture exhausted draw row delta",
    }
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-row-delta-terminal",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "post-ceiling-fpr-expression-source-model-synthesis-exhausted"
        ),
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "source_model_proof": {
            "source_family_synthesis": synthesis,
            "candidate_scores": [row],
            "terminal_blockers": list(synthesis["terminal_blockers"]),
        },
    }


def _draw_actionable_row_delta_source_model_without_child_subhunks() -> dict:
    source_hunks = [
        {
            "hunk_id": "post-meta-row-delta-local-h001",
            "base_start": 2561,
            "base_end": 2568,
            "candidate_start": 2561,
            "candidate_end": 2571,
            "removed": [
                "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;",
                "",
                "    digit_count = mn_GetDigitCount(value);",
                "    col_offset = (f32) col;",
                "    col_offset *= y_spacing;",
                "    rowf = (f32) row;",
                "    row_offset *= rowf;",
            ],
            "added": [
                "    {",
                "        f32 post_meta_row_delta;",
                "        post_meta_row_delta = HSD_JObjGetTranslationY(jobj2) - base;",
                "        row_offset = post_meta_row_delta;",
                "        digit_count = mn_GetDigitCount(value);",
                "        col_offset = (f32) col;",
                "        col_offset *= y_spacing;",
                "        rowf = (f32) row;",
                "        row_offset = post_meta_row_delta * rowf;",
                "    }",
            ],
            "kind": "motion",
            "risk": "high",
            "old_start": 2562,
            "old_end": 2568,
            "new_start": 2562,
            "new_end": 2571,
            "old_lines": [
                "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;",
                "",
                "    digit_count = mn_GetDigitCount(value);",
                "    col_offset = (f32) col;",
                "    col_offset *= y_spacing;",
                "    rowf = (f32) row;",
                "    row_offset *= rowf;",
            ],
            "new_lines": [
                "    {",
                "        f32 post_meta_row_delta;",
                "        post_meta_row_delta = HSD_JObjGetTranslationY(jobj2) - base;",
                "        row_offset = post_meta_row_delta;",
                "        digit_count = mn_GetDigitCount(value);",
                "        col_offset = (f32) col;",
                "        col_offset *= y_spacing;",
                "        rowf = (f32) row;",
                "        row_offset = post_meta_row_delta * rowf;",
                "    }",
            ],
        }
    ]
    row = {
        "candidate_id": (
            "post-meta-source-family-draw-row-translation-scale-split-"
            "row-delta-local"
        ),
        "dimension_id": "draw-row-translation-scale-split",
        "source_retained": "build/draw-row-delta.c",
        "pcdump_path": "build/draw-row-delta.pcdump.txt",
        "normalized_diff_lines": 0,
        "source_hunks": source_hunks,
        "target_score": {
            "matched": 1,
            "targeted": 3,
            "virtuals": {"32": {"expected": 28, "actual": 28, "matched": True}},
        },
        "expression_score": {
            "matched": 0,
            "targeted": 3,
            "false_positive_virtual_id_hit_count": 1,
            "virtuals": {
                "32": {
                    "status": "missing-expression",
                    "expected": 28,
                    "actual": None,
                }
            },
        },
    }
    return {
        "status": "actionable",
        "function": "mnDiagram_DrawCellNumber",
        "best_candidate": row,
        "ranked_candidates": [row],
        "candidates": [row],
        "score_rows": [row],
        "context": {"force_phys": {"32": 28, "37": 26, "46": 26}},
    }


def test_retained_frontiers_promotes_draw_protected_expression_subhunk_continuation() -> None:
    terminal = _draw_protected_subhunk_terminal(include_evidence=True)

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    frontier = meta["next_frontier"]
    continuation = frontier["continuation"]
    assert continuation["route"] == "draw-protected-expression-subhunk-reconcile"
    assert continuation["source_retained"] == "build/draw-row-delta.c"
    assert continuation["pcdump_path"] == "build/draw-row-delta.pcdump.txt"
    assert continuation["source_hunks"] == terminal["source_model_proof"][
        "source_family_synthesis"
    ]["candidate_scores"][0]["source_hunks"]
    assert continuation["target_score"]["matched"] == 1
    assert continuation["expression_score"]["matched"] == 0
    assert continuation["normalized_diff_lines"] == 0
    assert continuation["manual_subhunks"][0]["source_expression"] == (
        "row_offset_adj"
    )
    assert "--expression-score-json" in continuation["command"]
    assert "--structural-score-json" in continuation["command"]
    assert "--source-hunks-json" in continuation["command"]
    assert "manual-subhunk-range-required" in frontier[
        "protected_reconcile_terminal_blockers"
    ]


def test_retained_frontiers_upgrades_draw_row_delta_source_hunk_route(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "source_model_scored.json",
        _draw_actionable_row_delta_source_model_without_child_subhunks(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    continuation = payload["next_frontier"]["continuation"]
    assert continuation["route"] == "draw-protected-expression-subhunk-reconcile"
    assert continuation["source_retained"] == "build/draw-row-delta.c"
    assert continuation["source_hunks"][0]["hunk_id"] == (
        "post-meta-row-delta-local-h001"
    )
    assert continuation["protected_subhunks"]
    assert continuation["manual_subhunks"][0]["source_expression"] == "row_offset"
    assert continuation["manual_subhunks"][1]["source_expression"] == (
        "row_offset_adj"
    )
    assert "--source-hunks-json" in continuation["command"]


def _draw_blocked_protected_expression_reconcile_artifact() -> dict:
    return {
        "class_id": "protected-expression-structural-reconciliation",
        "status": "blocked",
        "generated_count": 14,
        "scored_count": 14,
        "anchor_requirements": [
            {"baseline_virtual": 32, "expected": 28, "label": "row_offset"},
            {"baseline_virtual": 37, "expected": 26, "label": "row_offset_adj"},
            {"baseline_virtual": 46, "expected": 26, "label": "lfd"},
        ],
        "terminal_blockers": [
            {
                "blocker": "manual-subhunk-range-required",
                "reason": "broad hunks crossed brace/control boundaries",
            },
            {
                "blocker": "all-recombines-lost-protected-anchors",
                "reason": "no recombine retained the protected expression anchors",
            },
        ],
        "generation_blockers": [
            {
                "blocker": "manual-subhunk-range-required",
                "hunk_id": "h002",
            }
        ],
        "candidates": [
            {
                "candidate_id": "reconcile-h001-h004",
                "preserved_anchor_count": 1,
                "normalized_diff_lines": 0,
                "structural_guard_accepted": True,
            }
        ],
        "frontiers": {
            "target_function": "mnDiagram_DrawCellNumber",
            "source_function": "mnDiagram_DrawCellNumber",
        },
    }


def test_retained_frontiers_reconcile_terminal_closes_draw_subhunk_replay(
    tmp_path: Path,
) -> None:
    terminal = _draw_protected_subhunk_terminal(include_evidence=True)
    first_pass = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )
    assert first_pass["status"] == "actionable"

    retained = _write_json(tmp_path / "retained_frontiers.json", first_pass)
    reconcile = _write_json(
        tmp_path / "reconcile_scored.json",
        _draw_blocked_protected_expression_reconcile_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[retained, reconcile],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    assert payload["next_frontier"] is None
    function_payload = payload["functions"][0]
    assert not [
        frontier
        for frontier in function_payload["frontiers"]
        if frontier.get("family_id") == "draw-protected-expression-subhunk-reconcile"
        and not frontier.get("terminal")
    ]
    terminal_frontiers = function_payload["terminal_frontiers"]
    assert any(
        frontier.get("family_id") == "draw-protected-expression-subhunk-reconcile"
        and frontier.get("terminal_reason")
        == (
            "draw-protected-expression-subhunk-reconcile-exhausted/"
            "protected-expression-not-retained"
        )
        for frontier in terminal_frontiers
    )

    meta = synthesize_retained_frontier_meta_ceiling(
        payload,
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    reconcile_groups = [
        group
        for group in meta["terminal_groups"]
        if group.get("family_id") == "draw-protected-expression-subhunk-reconcile"
    ]
    assert reconcile_groups
    assert reconcile_groups[0]["next_unsupported_source_family"] == (
        "draw-no-modeled-source-actionable-family-after-"
        "protected-expression-subhunk-reconcile"
    )
    assert meta["terminal_proof"]["next_unsupported_source_family"] == (
        "draw-no-modeled-source-actionable-family-after-"
        "protected-expression-subhunk-reconcile"
    )


def test_retained_frontiers_does_not_promote_draw_subhunk_without_source_evidence() -> None:
    terminal = _draw_protected_subhunk_terminal(include_evidence=False)

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    blockers = meta["terminal_proof"]["terminal_blockers"]
    assert "draw-protected-expression-subhunk-missing-source-evidence" in blockers


def test_stack_clean_handoff_survives_stale_helper_boundary_replay(
    tmp_path: Path,
) -> None:
    source_model = _draw_source_model_terminal_proof_with_synthesis()
    stack_model = (
        "Draw post-product/translate stack-clean/no-anchor recovery from "
        "an opcode-clean product/translate seed with stack-frame drift and "
        "missing IG32/IG37/IG46 expression anchors."
    )
    evidence = _draw_stack_clean_no_anchor_evidence()
    for target in (source_model, source_model["terminal_summary"]):
        target["next_unsupported_source_dimension"] = (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
        target["next_unsupported_source_family"] = (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
        target["next_unsupported_source_model"] = stack_model
        target["stack_clean_no_anchor_evidence"] = evidence
    source_model["terminal_summary"]["terminal_blocker"] = (
        "draw-post-all-known-loop-product-translate-expression-graph/"
        "no-target-or-real-expression-floor-improvement"
    )
    source_model["terminal_summary"]["terminal_reason"] = (
        "draw-post-all-known-loop-product-translate-expression-graph-exhausted/"
        "no-floor-improvement"
    )
    source_model["terminal_reason"] = source_model["terminal_summary"][
        "terminal_reason"
    ]
    source_model["source_model_proof"] = {
        "next_unsupported_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "next_unsupported_source_family": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "next_unsupported_source_model": stack_model,
        "stack_clean_no_anchor_evidence": evidence,
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "evidence_status": "artifact-synthesis-data",
            "attempted_equivalence_classes": [DRAW_PRODUCT_TRANSLATE_DIMENSION],
            "exhausted_dimensions": [
                {
                    "dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION,
                    "status": "scored-terminal",
                }
            ],
            "next_unsupported_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "next_unsupported_source_family": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "next_unsupported_source_model": stack_model,
            "stack_clean_no_anchor_evidence": evidence,
        },
    }

    artifacts = [
        _write_json(tmp_path / "draw" / "source_model.json", source_model),
        _write_json(
            tmp_path / "draw" / "stale_helper_boundary.json",
            {
                "status": "all-known-frontiers-exhausted",
                "functions": [
                    {
                        "function": "mnDiagram_DrawCellNumber",
                        "frontiers": [],
                        "terminal_frontiers": [
                            _draw_helper_boundary_completed_terminal(),
                        ],
                        "next_frontier": None,
                        "summary": {
                            "unexhausted_count": 0,
                            "terminal_count": 1,
                        },
                    }
                ],
            },
        ),
    ]

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=artifacts,
    )

    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "actionable"
    frontier = meta["next_frontier"]
    assert frontier["dimension_id"] == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    assert frontier["continuation"]["route"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert frontier["source_model_proof"]["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert frontier["source_model_proof"]["source_family_synthesis"][
        "next_unsupported_source_family"
    ] == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    assert meta["ranked_next_lanes"][0]["dimension_id"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )


def test_retained_frontiers_prefers_stack_clean_final_over_stale_helper_terminal() -> None:
    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        _draw_helper_boundary_completed_terminal(),
                        _draw_product_translate_terminal_with_stack_clean_evidence(),
                        _draw_stack_clean_no_anchor_completed_terminal(),
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 3},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    proof = meta["terminal_proof"]
    assert proof["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert meta["terminal_groups"][0]["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert any(
        group["family_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        for group in meta["terminal_groups"]
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )


def test_retained_frontiers_file_triage_consumes_stack_clean_terminal_artifact(
    tmp_path: Path,
) -> None:
    artifacts = [
        _write_json(
            tmp_path / "draw" / "stack-clean-final.json",
            _draw_stack_clean_no_anchor_completed_terminal(),
        ),
        _write_json(
            tmp_path / "draw" / "stale-helper-boundary.json",
            _draw_helper_boundary_completed_terminal(),
        ),
    ]

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=artifacts,
    )

    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    assert proof["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert any(
        group["family_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        for group in meta["terminal_groups"]
    )


def test_stack_clean_no_anchor_recovery_lane_survives_parent_terminal_signature() -> None:
    product_translate_terminal = (
        _draw_product_translate_terminal_with_stack_clean_evidence()
    )
    first_pass = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [product_translate_terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )
    stack_clean_lane = first_pass["next_frontier"]

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "actionable",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [stack_clean_lane],
                    "terminal_frontiers": [product_translate_terminal],
                    "next_frontier": stack_clean_lane,
                    "summary": {"unexhausted_count": 1, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    assert meta["next_frontier"]["dimension_id"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )


def test_stack_clean_completed_terminal_suppresses_consumed_recovery_lane() -> None:
    product_translate_terminal = (
        _draw_product_translate_terminal_with_stack_clean_evidence()
    )
    first_pass = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [product_translate_terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )
    stack_clean_lane = first_pass["next_frontier"]
    stack_clean_terminal = _draw_stack_clean_no_anchor_completed_terminal()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "actionable",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [stack_clean_lane],
                    "terminal_frontiers": [stack_clean_terminal],
                    "next_frontier": stack_clean_lane,
                    "summary": {"unexhausted_count": 1, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []
    proof = meta["terminal_proof"]
    assert proof["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert proof["stack_clean_no_anchor_evidence"]["seed_candidate_id"] == (
        _draw_stack_clean_no_anchor_evidence()["seed_candidate_id"]
    )


def test_stack_clean_terminal_summary_only_closes_consumed_recovery_lane() -> None:
    product_translate_terminal = (
        _draw_product_translate_terminal_with_stack_clean_evidence()
    )
    first_pass = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [product_translate_terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )
    stack_clean_lane = first_pass["next_frontier"]
    stack_clean_terminal = _draw_stack_clean_no_anchor_terminal_summary_only()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "actionable",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [stack_clean_lane],
                    "terminal_frontiers": [stack_clean_terminal],
                    "next_frontier": stack_clean_lane,
                    "summary": {"unexhausted_count": 1, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []
    proof = meta["terminal_proof"]
    assert proof["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert proof["stack_clean_no_anchor_evidence"]["seed_candidate_id"] == (
        _draw_stack_clean_no_anchor_evidence()["seed_candidate_id"]
    )


def test_retained_frontiers_file_triage_consumes_stack_clean_terminal_artifact(
    tmp_path: Path,
) -> None:
    product_translate_path = _write_json(
        tmp_path / "draw_product_translate_terminal.json",
        _draw_product_translate_terminal_with_stack_clean_evidence(),
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[product_translate_path],
        functions=["mnDiagram_DrawCellNumber"],
    )
    stale_frontier = first_payload["functions"][0]["next_frontier"]
    assert stale_frontier["dimension_id"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )

    retained_path = _write_json(
        tmp_path / "draw_frontiers_after_stack_clean_handoff.json",
        first_payload,
    )
    stack_clean_terminal_path = _write_json(
        tmp_path / "source_model_stack_clean_recovery.json",
        _draw_stack_clean_no_anchor_terminal_summary_only(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[retained_path, stack_clean_terminal_path],
        functions=["mnDiagram_DrawCellNumber"],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    assert not any(
        frontier.get("dimension_id") == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        for frontier in function_payload["frontiers"]
    )
    assert function_payload["summary"]["suppressed_by_terminal_count"] == 1
    meta = function_payload["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []
    assert not any(
        lane.get("dimension_id") == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        for lane in meta["ranked_next_lanes"]
    )
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )


def test_stack_clean_no_anchor_terminal_replaces_product_translate_final_family() -> None:
    product_translate_terminal = (
        _draw_product_translate_terminal_with_stack_clean_evidence()
    )
    stack_clean_terminal = _draw_stack_clean_no_anchor_completed_terminal()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        product_translate_terminal,
                        stack_clean_terminal,
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    proof = meta["terminal_proof"]
    assert proof["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY
    )
    assert proof["stack_clean_no_anchor_evidence"]["seed_candidate_id"] == (
        _draw_stack_clean_no_anchor_evidence()["seed_candidate_id"]
    )


def test_post_stack_clean_source_shape_terminal_beats_stack_clean_recovery_terminal() -> None:
    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        _draw_stack_clean_no_anchor_completed_terminal(),
                        _draw_post_stack_clean_no_anchor_source_shape_completed_terminal(),
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert proof["post_stack_clean_no_anchor_evidence"]
    assert {
        row["dimension_id"]
        for row in proof["source_family_synthesis"]["exhausted_dimensions"]
    } == {DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION}
    assert meta["terminal_groups"][0]["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_post_stack_clean_source_shape_terminal_merge_order_independent() -> None:
    old_terminal = _draw_stack_clean_no_anchor_completed_terminal()
    new_terminal = _draw_post_stack_clean_no_anchor_source_shape_completed_terminal()

    for terminal_frontiers in ([old_terminal, new_terminal], [new_terminal, old_terminal]):
        meta = synthesize_retained_frontier_meta_ceiling(
            {
                "status": "all-known-frontiers-exhausted",
                "functions": [
                    {
                        "function": "mnDiagram_DrawCellNumber",
                        "frontiers": [],
                        "terminal_frontiers": terminal_frontiers,
                        "next_frontier": None,
                        "summary": {"unexhausted_count": 0, "terminal_count": 2},
                    }
                ],
            },
            function="mnDiagram_DrawCellNumber",
        )
        assert meta["terminal_proof"]["next_unsupported_source_family"] == (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
        )


def test_post_stack_loop_callsite_terminal_beats_source_shape_terminal() -> None:
    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        _draw_post_stack_clean_no_anchor_source_shape_completed_terminal(),
                        _draw_post_stack_loop_callsite_source_context_completed_terminal(),
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    assert proof["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert proof["post_stack_clean_no_anchor_evidence"]
    assert {
        row["dimension_id"]
        for row in proof["source_family_synthesis"]["exhausted_dimensions"]
    } == {DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION}
    assert meta["terminal_groups"][0]["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )


def test_post_stack_loop_callsite_terminal_not_downgraded_by_nested_post_stack_evidence() -> None:
    terminal = _draw_post_stack_loop_callsite_source_context_completed_terminal()
    terminal["source_model_proof"]["source_family_synthesis"][
        "post_stack_clean_no_anchor_evidence"
    ] = terminal["post_stack_clean_no_anchor_evidence"]

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert proof["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_retained_frontiers_accepts_draw_post_row_offset_owner_lifetime_actionable_lane() -> None:
    candidate = {
        "candidate_id": (
            "draw-post-row-offset-owner-expression-lifetime-"
            "row-offset-adj-callsite-owner"
        ),
        "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
        "source_retained": "build/draw/post-row-offset-lifetime.c",
        "pcdump_path": "build/draw/post-row-offset-lifetime.pcdump.txt",
        "source_hunks": [{"hunk_id": "post-row-offset-lifetime"}],
        "target_score": {"matched": 1, "targeted": 3},
        "expression_score": {"matched": 1, "targeted": 3},
    }
    lane = {
        "frontier_id": "draw-post-row-offset-lifetime-actionable",
        "function": "mnDiagram_DrawCellNumber",
        "family_id": "post-ceiling-baseline-escape-continuation",
        "suppression_family": "post-ceiling-baseline-escape-continuation",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "terminal": False,
        "actionable": True,
        "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
        "source_model_layer_dimension_id": (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        ),
        "attempted_targets": {"32": 28, "37": 26, "46": 26},
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "continuation": {
            "route": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
            "candidate_id": candidate["candidate_id"],
            "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
            "source_retained": candidate["source_retained"],
            "pcdump_path": candidate["pcdump_path"],
            "source_hunks": candidate["source_hunks"],
            "target_score": candidate["target_score"],
            "expression_score": candidate["expression_score"],
            "command": "melee-agent debug search source-family-continuation --json",
        },
        "best_candidate": candidate,
        "source_model_proof": {
            "candidate_scores": [candidate],
            "source_family_synthesis": {
                "attempted_equivalence_classes": [
                    DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
                ],
                "retained_scored_probes": [candidate],
            },
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "actionable",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [lane],
                    "terminal_frontiers": [],
                    "next_frontier": lane,
                    "summary": {"unexhausted_count": 1, "terminal_count": 0},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    frontier = meta["next_frontier"]
    assert frontier["dimension_id"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    continuation = frontier["continuation"]
    assert continuation["source_retained"] == candidate["source_retained"]
    assert continuation["pcdump_path"] == candidate["pcdump_path"]
    assert continuation["source_hunks"] == candidate["source_hunks"]
    assert continuation["target_score"] == candidate["target_score"]
    assert continuation["expression_score"] == candidate["expression_score"]


def test_retained_frontiers_terminal_prefers_lifetime_over_consumed_owner_split() -> None:
    owner_terminal = _draw_post_stack_loop_callsite_owner_split_completed_terminal()
    lifetime_terminal = _draw_post_row_offset_owner_expression_lifetime_completed_terminal()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [owner_terminal, lifetime_terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    )
    assert proof["exhausted_source_dimension"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
    )


def test_retained_frontiers_file_triage_promotes_post_stack_source_shape_artifact(
    tmp_path: Path,
) -> None:
    old_path = _write_json(
        tmp_path / "draw" / "stack-clean-final.json",
        _draw_stack_clean_no_anchor_completed_terminal(),
    )
    new_path = _write_json(
        tmp_path / "draw" / "post-stack-source-shape-final.json",
        _draw_post_stack_clean_no_anchor_source_shape_completed_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[old_path, new_path],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    proof = function_payload["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert proof["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )


def test_retained_meta_promotes_newer_direct_post_product_terminal_over_stale_post_stack(
    tmp_path: Path,
) -> None:
    old_aggregate = {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": [],
                "terminal_frontiers": [
                    _draw_post_stack_clean_no_anchor_source_shape_completed_terminal()
                ],
                "next_frontier": None,
                "summary": {"unexhausted_count": 0, "terminal_count": 1},
            }
        ],
    }
    old_path = _write_json(tmp_path / "old-post-stack.json", old_aggregate)
    new_path = _write_json(
        tmp_path / "new-post-product-terminal.json",
        _draw_stack_clean_no_anchor_completed_terminal(),
    )
    os.utime(old_path, (1000, 1000))
    os.utime(new_path, (2000, 2000))

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[old_path, new_path],
    )

    meta_ceiling = payload["functions"][0]["meta_ceiling"]
    proof = meta_ceiling["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert proof["terminal_reason"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert meta_ceiling["terminal_groups"][0]["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_retained_meta_keeps_newer_direct_post_stack_terminal_when_it_is_current(
    tmp_path: Path,
) -> None:
    old_path = _write_json(
        tmp_path / "old-post-product-terminal.json",
        _draw_stack_clean_no_anchor_completed_terminal(),
    )
    new_path = _write_json(
        tmp_path / "new-post-stack-terminal.json",
        _draw_post_stack_clean_no_anchor_source_shape_completed_terminal(),
    )
    os.utime(old_path, (1000, 1000))
    os.utime(new_path, (2000, 2000))

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[old_path, new_path],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert proof["terminal_reason"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )


def test_retained_meta_ignores_nested_stale_context_current_ceiling_when_top_level_terminal_is_newer(
    tmp_path: Path,
) -> None:
    top_level_terminal = _draw_stack_clean_no_anchor_completed_terminal()
    top_level_terminal["context"] = {
        "current_ceiling": {
            "function": "mnDiagram_DrawCellNumber",
            "frontier_id": "stale-context-current-ceiling",
            "family_id": "post-ceiling-fpr-expression-source-model-synthesis",
            "status": "terminal",
            "terminal": True,
            "terminal_reason": (
                DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
            ),
            "attempted_targets": {"32": 28, "37": 26, "46": 26},
            "source_model_proof": (
                _draw_post_stack_clean_no_anchor_source_shape_completed_terminal()[
                    "source_model_proof"
                ]
            ),
        }
    }
    path = _write_json(
        tmp_path / "post-product-with-stale-context.json",
        top_level_terminal,
    )
    os.utime(path, (2000, 2000))

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[path],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert proof["terminal_reason"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )


def test_draw_helper_boundary_handoff_frontier_follows_stack_clean_terminal() -> None:
    stack_clean_terminal = _draw_stack_clean_no_anchor_completed_terminal()
    helper_terminal = _draw_helper_boundary_terminal_continuation()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [
                        stack_clean_terminal,
                        helper_terminal,
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "actionable"
    assert retained_frontier_meta_rank(meta)[0] == 13
    frontier = meta["next_frontier"]
    assert frontier["dimension_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    assert frontier["family_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    assert frontier["unsupported_source_expression_class"] == (
        DRAW_COUPLED_UNSUPPORTED_CLASS
    )

    continuation = frontier["continuation"]
    assert continuation["route"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    assert "melee-agent debug suggest inlines" in continuation["command"]
    assert "--verify --json" in continuation["command"]
    command = shlex.split(continuation["command"])
    assert command[command.index("--source-file") + 1] == (
        "build/draw/helper-boundary-seed.c"
    )
    assert command[command.index("--pcdump") + 1] == (
        "build/draw/helper-boundary-seed.pcdump.txt"
    )
    assert continuation["pcdump_path"] == "build/draw/helper-boundary-seed.pcdump.txt"
    assert continuation["source_retained"] == "build/draw/helper-boundary-seed.c"
    assert continuation["source_hunks"] == [{"hunk_id": "helper-boundary-seed"}]
    assert continuation["target_score"]["matched"] == 0
    assert continuation["expression_score"]["matched"] == 0
    assert continuation["stack_frame_facts"]["frame_delta"] == 8
    assert continuation["next_unsupported_source_model"] == (
        DRAW_COUPLED_UNSUPPORTED_MODEL
    )
    assert frontier["source_model_proof"]["next_unsupported_source_dimension"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )


def test_draw_helper_boundary_requires_concrete_source_and_pcdump_evidence() -> None:
    abstract_terminal = _draw_helper_boundary_abstract_terminal_continuation()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [abstract_terminal],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 1},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []


def test_draw_helper_boundary_terminal_closes_handoff_frontier() -> None:
    helper_terminal = _draw_helper_boundary_terminal_continuation()
    helper_closure = _draw_helper_boundary_completed_terminal()

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [],
                    "terminal_frontiers": [helper_terminal, helper_closure],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    proof = meta["terminal_proof"]
    assert proof["exhausted_source_dimension"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert "next_unsupported_source_dimension" not in proof
    assert proof["next_unsupported_source_family"] == DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    assert proof["next_unsupported_source_model"] == DRAW_HELPER_BOUNDARY_FINAL_MODEL
    assert any(
        group["family_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        and group["terminal_reason"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
        for group in meta["terminal_groups"]
    )


def test_draw_helper_boundary_suggest_inlines_terminal_closes_raw_handoff(
    tmp_path: Path,
) -> None:
    helper_terminal = _draw_helper_boundary_terminal_continuation()
    suggest_terminal = _draw_helper_boundary_suggest_inlines_terminal_report()
    helper_path = tmp_path / "source_family_continuation.json"
    suggest_path = tmp_path / "suggest_inlines_terminal.json"
    helper_path.write_text(json.dumps(helper_terminal), encoding="utf-8")
    suggest_path.write_text(json.dumps(suggest_terminal), encoding="utf-8")

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[helper_path, suggest_path],
        functions=["mnDiagram_DrawCellNumber"],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    assert function_payload["frontiers"] == []
    terminal = next(
        row
        for row in function_payload["terminal_frontiers"]
        if row["kind"]
        == "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal"
    )
    assert terminal["terminal_blocker"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
    assert terminal["candidate_ids"] == ["void-helper-0001", "void-helper-0002"]

    meta = function_payload["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    proof = meta["terminal_proof"]
    assert proof["terminal_blocker"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
    assert proof["exhausted_source_dimension"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert "next_unsupported_source_dimension" not in proof
    assert proof["next_unsupported_source_family"] == DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    assert proof["next_unsupported_source_model"] == DRAW_HELPER_BOUNDARY_FINAL_MODEL
    assert any(
        blocker["reason"] == DRAW_HELPER_BOUNDARY_REJECTION_REASON
        for blocker in proof["terminal_blockers"]
    )
    assert any(
        group["family_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        and group["terminal_reason"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
        for group in meta["terminal_groups"]
    )


def test_draw_helper_boundary_suggest_inlines_terminal_suppresses_emitted_handoff(
    tmp_path: Path,
) -> None:
    helper_terminal = _draw_helper_boundary_terminal_continuation()
    helper_path = _write_json(
        tmp_path / "source_family_continuation.json",
        helper_terminal,
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[helper_path],
        functions=["mnDiagram_DrawCellNumber"],
    )
    stale_frontier = first_payload["functions"][0]["next_frontier"]
    assert stale_frontier["suppression_family"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )

    retained_path = _write_json(
        tmp_path / "draw_frontiers_after_helper_handoff.json",
        first_payload,
    )
    suggest_path = _write_json(
        tmp_path / "suggest_inlines_terminal.json",
        _draw_helper_boundary_suggest_inlines_terminal_report(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[retained_path, suggest_path],
        functions=["mnDiagram_DrawCellNumber"],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    assert not any(frontier["actionable"] for frontier in function_payload["frontiers"])
    assert not any(
        frontier.get("suppression_family") == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        for frontier in function_payload["frontiers"]
    )
    assert function_payload["summary"]["suppressed_by_terminal_count"] == 1
    suppressed = next(
        row for row in function_payload["terminal_frontiers"]
        if row["frontier_id"] == stale_frontier["frontier_id"]
    )
    assert suppressed["suppressed_by_terminal"] is True
    assert suppressed["terminal_reason"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
    assert suppressed["closed_by"] == [str(suggest_path)]

    meta = function_payload["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert any(
        group["family_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        and group["terminal_reason"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
        for group in meta["terminal_groups"]
    )


def test_draw_helper_boundary_retained_score_rows_close_raw_handoff(
    tmp_path: Path,
) -> None:
    helper_terminal = _draw_helper_boundary_terminal_continuation()
    helper_path = _write_json(
        tmp_path / "source_family_continuation.json",
        helper_terminal,
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[helper_path],
        functions=["mnDiagram_DrawCellNumber"],
    )
    stale_frontier = first_payload["functions"][0]["next_frontier"]
    assert stale_frontier["suppression_family"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )

    retained_path = _write_json(
        tmp_path / "draw_frontiers_after_helper_handoff.json",
        first_payload,
    )
    score_rows_path = _write_json(
        tmp_path / "suggest_inlines_retained_source.json",
        _draw_helper_boundary_suggest_inlines_retained_score_rows(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[retained_path, score_rows_path],
        functions=["mnDiagram_DrawCellNumber"],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    assert not any(frontier["actionable"] for frontier in function_payload["frontiers"])
    assert not any(
        frontier.get("suppression_family") == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        for frontier in function_payload["frontiers"]
    )
    assert function_payload["summary"]["suppressed_by_terminal_count"] == 1
    terminal = next(
        row
        for row in function_payload["terminal_frontiers"]
        if row["kind"]
        == "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal"
        and row["terminal_reason"]
        == DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
    )
    assert terminal["candidate_ids"] == [
        "block-macro-0001",
        "scalar-return-helper-0001",
    ]
    assert terminal["score_coverage"]["best_target_matched"] == 1
    assert terminal["score_coverage"]["best_expression_matched"] == 0
    proof = terminal["source_model_proof"]
    assert proof["terminal_blocker"] == (
        DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
    )
    assert proof["closed_families"] == [DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION]
    assert proof["exhausted_source_dimension"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert "next_unsupported_source_dimension" not in proof
    assert proof["next_unsupported_source_family"] == DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    assert proof["next_unsupported_source_model"] == DRAW_HELPER_BOUNDARY_FINAL_MODEL
    assert proof["source_family_synthesis"]["next_unsupported_source_family"] == (
        DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    )
    assert any(
        row["dimension_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        and row["exhaustion_reason"]
        == DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        for row in proof["source_family_synthesis"]["exhausted_dimensions"]
    )

    suppressed = next(
        row for row in function_payload["terminal_frontiers"]
        if row["frontier_id"] == stale_frontier["frontier_id"]
    )
    assert suppressed["suppressed_by_terminal"] is True
    assert suppressed["terminal_reason"] == (
        DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
    )
    assert suppressed["closed_by"] == [str(score_rows_path)]


def test_draw_helper_boundary_retained_score_rows_close_live_expression_floor(
    tmp_path: Path,
) -> None:
    helper_terminal = _draw_helper_boundary_terminal_continuation()
    helper_path = _write_json(
        tmp_path / "source_family_continuation.json",
        helper_terminal,
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[helper_path],
        functions=["mnDiagram_DrawCellNumber"],
    )
    stale_frontier = first_payload["functions"][0]["next_frontier"]

    score_artifact = _draw_helper_boundary_suggest_inlines_retained_score_rows(
        expression_matched=1,
    )
    for row in score_artifact["score_rows"]:
        row["target_matched"] = 0
        row["target_virtual_distance"] = 3
        row["target_score"]["matched"] = 0
        row["target_score"]["virtual_distance"] = 3
        for virtual in row["target_score"]["virtuals"].values():
            virtual["matched"] = False
        row["structural_guard"] = {
            "accepted": False,
            "classification_primary": "stack-layout",
            "normalized_diff_lines": 0,
            "frame_delta": 8,
            "rejection_reason": "checkdiff structural drift: stack-layout",
        }
    score_artifact["score_rows"][1]["expression_matched"] = 0
    score_artifact["score_rows"][1]["expression_score"]["matched"] = 0

    retained_path = _write_json(
        tmp_path / "draw_frontiers_after_helper_handoff.json",
        first_payload,
    )
    score_rows_path = _write_json(
        tmp_path / "suggest_inlines_retained_source.json",
        score_artifact,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[retained_path, score_rows_path],
        functions=["mnDiagram_DrawCellNumber"],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    terminal = next(
        row
        for row in function_payload["terminal_frontiers"]
        if row.get("frontier_id") != stale_frontier["frontier_id"]
        and row["kind"]
        == "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal"
    )
    assert terminal["score_coverage"]["best_target_matched"] == 0
    assert terminal["score_coverage"]["best_expression_matched"] == 1
    assert terminal["score_coverage"]["expression_improved_rows"] == 1
    suppressed = next(
        row for row in function_payload["terminal_frontiers"]
        if row["frontier_id"] == stale_frontier["frontier_id"]
    )
    assert suppressed["suppressed_by_terminal"] is True
    assert suppressed["terminal_reason"] == (
        DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
    )


def test_draw_helper_boundary_closed_family_suppresses_emitted_handoff(
    tmp_path: Path,
) -> None:
    helper_terminal = _draw_helper_boundary_terminal_continuation()
    helper_path = _write_json(
        tmp_path / "source_family_continuation.json",
        helper_terminal,
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[helper_path],
        functions=["mnDiagram_DrawCellNumber"],
    )
    stale_frontier = first_payload["functions"][0]["next_frontier"]
    replay_payload = json.loads(json.dumps(first_payload))
    replay_payload["functions"][0]["meta_ceiling"]["closed_families"] = [
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    ]
    retained_path = _write_json(
        tmp_path / "draw_frontiers_with_closed_helper_family.json",
        replay_payload,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        artifacts=[retained_path],
        functions=["mnDiagram_DrawCellNumber"],
    )

    function_payload = payload["functions"][0]
    assert payload["status"] == "all-known-frontiers-exhausted"
    assert function_payload["next_frontier"] is None
    suppressed = next(
        row for row in function_payload["terminal_frontiers"]
        if row["frontier_id"] == stale_frontier["frontier_id"]
    )
    assert suppressed["suppressed_by_terminal"] is True
    assert suppressed["terminal_reason"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON


def test_post_ceiling_source_model_terminal_proof_enriches_extracted_draw_proof(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "draw" / "baseline_escape_full_closure.json",
        _draw_source_model_terminal_proof(),
    )
    first_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )
    extracted_proof = next(
        frontier for frontier in first_payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    extracted_artifact = _write_json(
        tmp_path / "draw" / "source_model_terminal_proof.json",
        extracted_proof,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[extracted_artifact],
    )

    proof = next(
        frontier for frontier in payload["functions"][0]["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    assert proof["kind"] == "post-ceiling-fpr-expression-source-model-proof"
    source_model = proof["source_model_proof"]
    synthesis = source_model["source_family_synthesis"]
    assert synthesis["evidence_status"] == "fallback-inferred-from-local-candidates"
    assert synthesis["attempted_equivalence_classes"] == [
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
    ]
    assert "source-family discovery or plateau data" in (
        synthesis["next_unsupported_source_model"]
    )


def test_post_ceiling_source_model_terminal_proof_preserves_draw_synthesis_data(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "draw" / "baseline_escape_synthesis_closure.json",
        _draw_source_model_terminal_proof_with_synthesis(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    proof = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-source-model-proof"
    )
    assert proof["kind"] == (
        "post-ceiling-fpr-expression-source-model-synthesis-proof"
    )
    assert proof["terminal_reason"] == (
        "post-ceiling-fpr-expression-source-model-synthesis-exhausted"
    )
    assert proof["attempted_targets"] == {"32": 28, "37": 26, "46": 26}
    assert proof["metrics"]["candidate_count"] > 3

    source_model = proof["source_model_proof"]
    synthesis = source_model["source_family_synthesis"]
    assert synthesis["evidence_status"] == "artifact-synthesis-data"
    assert synthesis["forced_target_map"] == {"32": 28, "37": 26, "46": 26}
    assert synthesis["attempted_equivalence_classes"] == [
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
    ]
    assert set(synthesis["generated_candidate_ids"]) == {
        "post-ceiling-source-family-draw-col-cast-product-local",
        "post-ceiling-source-family-draw-row-translation-scale-split",
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
    }
    assert set(synthesis["scored_candidate_ids"]) >= {
        "post-ceiling-source-family-draw-col-cast-product-local",
        "post-ceiling-source-family-draw-row-translation-scale-split",
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
    }
    assert set(synthesis["all_candidate_ids"]) >= {
        "post-ceiling-paired-offset-block",
        "post-ceiling-digit-anim-callarg-block",
        "post-ceiling-source-family-draw-col-cast-product-local",
        "post-ceiling-source-family-draw-row-translation-scale-split",
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
    }
    assert synthesis["candidate_count"] > 3
    assert synthesis["source_hunks_by_candidate"][0]["source_hunks"][0][
        "hunk_id"
    ] == "draw-col-cast-product-local-h0"
    assert synthesis["retained_scored_probes"][0]["candidate_id"] == (
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp"
    )
    assert synthesis["missing_inputs"] == [
        {"input": "draw_expression_materializer", "reason": "fixture-omitted"}
    ]
    assert {
        row["dimension_id"] for row in synthesis["missing_dimensions"]
    } == {
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
        DRAW_POST_SOURCE_CONTEXT_DIMENSION,
    }
    assert {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    } == {
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
    }
    assert synthesis["next_unsupported_source_model"] == (
        "fixture: broader Draw FPR expression source model remains "
        "unsupported"
    )
    assert source_model["next_unsupported_source_model"] == (
        synthesis["next_unsupported_source_model"]
    )


def test_post_ceiling_select_order_route_terminals_close_sort_continuation(
    tmp_path: Path,
) -> None:
    continuation = _write_json(
        tmp_path / "sort" / "baseline_escape_continuation.json",
        _post_ceiling_route_continuation(tmp_path),
    )
    init_terminal = _write_json(
        tmp_path / "sort" / "init_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            candidate_id="post-ceiling-sort-init-pointer-walk",
        ),
    )
    swap_terminal = _write_json(
        tmp_path / "sort" / "swap_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            candidate_id="post-ceiling-sort-swap-materialization",
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[continuation, init_terminal, swap_terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    assert fn["next_frontier"] is None
    terminal = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-baseline-escape-continuation"
    )
    assert terminal["suppressed_by_terminal"] is True
    assert terminal["terminal_reason"] == (
        "post-ceiling-continuation-routes-exhausted/"
        "current-source-shape-ceiling"
    )
    assert set(terminal["closed_by"]) == {
        str(init_terminal),
        str(swap_terminal),
    }
    assert {row["terminal_blocker"] for row in terminal["route_terminal_blockers"]} == {
        "transform-family-exhausted",
    }


def test_post_ceiling_select_order_route_terminals_close_draw_continuation(
    tmp_path: Path,
) -> None:
    continuation = _write_json(
        tmp_path / "draw" / "baseline_escape_continuation.json",
        _post_ceiling_route_continuation(
            tmp_path,
            function="mnDiagram_DrawCellNumber",
            class_id=1,
            parent_force={"32": 28, "37": 26, "46": 26},
            route_specs=[
                (
                    "post-ceiling-digit-anim-callarg-block",
                    [[33, 46]],
                    {"33": 28, "37": 26, "46": 26},
                ),
                (
                    "post-ceiling-paired-offset-block",
                    [[33, 48]],
                    {"33": 28, "46": 26, "48": 26},
                ),
            ],
        ),
    )
    digit_terminal = _write_json(
        tmp_path / "draw" / "digit_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            function="mnDiagram_DrawCellNumber",
            class_id=1,
            candidate_id="post-ceiling-digit-anim-callarg-block",
            target_orders=[[33, 46]],
            force={"33": 28, "37": 26, "46": 26},
            kind="degree-zero-fpr-case-c-source-exhaustion",
        ),
    )
    paired_terminal = _write_json(
        tmp_path / "draw" / "paired_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            function="mnDiagram_DrawCellNumber",
            class_id=1,
            candidate_id="post-ceiling-paired-offset-block",
            target_orders=[[33, 48]],
            force={"33": 28, "46": 26, "48": 26},
            kind="degree-zero-fpr-case-c-source-exhaustion",
            terminal_blocker="ranked-owner-candidates-not-materializable",
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[continuation, digit_terminal, paired_terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    terminal = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "post-ceiling-baseline-escape-continuation"
    )
    assert terminal["suppressed_by_terminal"] is True
    assert {row["terminal_blocker"] for row in terminal["route_terminal_blockers"]} == {
        "transform-family-exhausted",
        "ranked-owner-candidates-not-materializable",
    }


def test_post_ceiling_continuation_stays_open_until_all_routes_close(
    tmp_path: Path,
) -> None:
    continuation = _write_json(
        tmp_path / "sort" / "baseline_escape_continuation.json",
        _post_ceiling_route_continuation(tmp_path),
    )
    terminal = _write_json(
        tmp_path / "sort" / "init_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            candidate_id="post-ceiling-sort-init-pointer-walk",
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[continuation, terminal],
    )

    assert payload["status"] == "actionable"
    fn = payload["functions"][0]
    continuation_frontier = next(
        frontier for frontier in fn["frontiers"]
        if frontier["family_id"] == "post-ceiling-baseline-escape-continuation"
    )
    assert continuation_frontier["suppressed_by_terminal"] is False
    assert fn["next_frontier"]["family_id"] == (
        "post-ceiling-baseline-escape-continuation"
    )


def test_same_force_route_terminal_with_different_pcdump_does_not_close_parent(
    tmp_path: Path,
) -> None:
    continuation = _write_json(
        tmp_path / "sort" / "baseline_escape_continuation.json",
        _post_ceiling_route_continuation(tmp_path),
    )
    wrong_terminal = _write_json(
        tmp_path / "sort" / "wrong_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            candidate_id="post-ceiling-sort-init-pointer-walk",
            pcdump_suffix=".different.pcdump.txt",
        ),
    )
    swap_terminal = _write_json(
        tmp_path / "sort" / "swap_select_order.json",
        _post_ceiling_select_order_terminal(
            tmp_path,
            candidate_id="post-ceiling-sort-swap-materialization",
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[continuation, wrong_terminal, swap_terminal],
    )

    assert payload["status"] == "actionable"
    fn = payload["functions"][0]
    continuation_frontier = next(
        frontier for frontier in fn["frontiers"]
        if frontier["family_id"] == "post-ceiling-baseline-escape-continuation"
    )
    assert continuation_frontier["suppressed_by_terminal"] is False
    nested_route = next(
        frontier for frontier in fn["frontiers"]
        if frontier["family_id"] == "retained-source-select-order-repair"
        and frontier.get("post_ceiling_route_signature")
        and "post-ceiling-sort-init-pointer-walk" in str(
            frontier.get("source_file")
        )
    )
    assert nested_route["suppressed_by_terminal"] is False
    assert nested_route["terminal"] is False


def test_select_order_terminal_exhaustion_does_not_close_mismatched_handoff(
    tmp_path: Path,
) -> None:
    handoff = _write_json(
        tmp_path / "draw" / "node_set_split_resumed.json",
        _draw_node_set_select_order_handoff(tmp_path),
    )
    terminal_payload = _draw_select_order_case_c_terminal()
    terminal_payload["terminal_exhaustion_summary"]["force_phys_targets"] = {
        "32": 29,
        "37": 26,
        "46": 26,
    }
    terminal = _write_json(
        tmp_path / "draw" / "select_order_mismatch.json",
        terminal_payload,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[handoff, terminal],
    )

    assert payload["status"] == "actionable"
    fn = payload["functions"][0]
    assert fn["next_frontier"]["artifact"] == str(handoff)
    assert len(fn["frontiers"]) == 1
    assert fn["frontiers"][0]["family_id"] == "retained-source-select-order-repair"
    assert fn["frontiers"][0]["suppressed_by_terminal"] is False


def test_public_select_order_frontier_closes_on_zero_hit_terminal(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "draw" / "retained-frontiers.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [
                        {
                            "frontier_id": "public-select-order-stale",
                            "function": "mnDiagram_DrawCellNumber",
                            "family_id": "retained-source-select-order-repair",
                            "kind": "retained-source-select-order-repair",
                            "status": "",
                            "terminal": False,
                            "attempted_targets": {"32": 28},
                            "protected_targets": {"37": 26, "46": 26},
                            "continuation": {
                                "route": "score-source",
                                "source_retained": str(tmp_path / "draw.c"),
                                "command": (
                                    "melee-agent debug target score-source "
                                    f"{tmp_path / 'draw.c'} "
                                    "--function mnDiagram_DrawCellNumber "
                                    "--json --retain-pcdump"
                                ),
                            },
                        }
                    ],
                    "terminal_frontiers": [],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 1},
                }
            ],
        },
    )
    terminal_payload = _draw_select_order_case_c_terminal()
    terminal_payload["terminal_exhaustion_summary"]["blocker_targets"] = [46]
    terminal_payload["terminal_exhaustion_summary"]["diagnostic_bucket_counts"] = {
        "force-phys-hit-32": 0,
        "force-phys-hit-37": 0,
        "force-phys-hit-46": 0,
    }
    terminal = _write_json(
        tmp_path / "draw" / "select-order-terminal.json",
        terminal_payload,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[stale, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    closed = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["frontier_id"] == "public-select-order-stale"
    )
    assert closed["suppressed_by_terminal"] is True
    assert closed["terminal_reason"] == "transform-family-exhausted"
    assert str(terminal) in closed["closed_by"]


def test_public_no_route_frontiers_do_not_become_next_actions(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "draw" / "nested-retained-frontiers.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [
                        {
                            "frontier_id": "public-empty-select-order",
                            "function": "mnDiagram_DrawCellNumber",
                            "family_id": "retained-source-select-order-repair",
                            "kind": "retained-source-select-order-repair",
                            "terminal": False,
                            "attempted_targets": {},
                            "protected_targets": {},
                            "continuation": {
                                "route": "score-source",
                                "source_retained": str(tmp_path / "draw.c"),
                                "command": (
                                    "melee-agent debug target score-source "
                                    f"{tmp_path / 'draw.c'} "
                                    "--function mnDiagram_DrawCellNumber "
                                    "--json --retain-pcdump"
                                ),
                            },
                        },
                        {
                            "frontier_id": "public-empty-post-ceiling",
                            "function": "mnDiagram_DrawCellNumber",
                            "family_id": (
                                "post-ceiling-baseline-escape-continuation"
                            ),
                            "kind": "post-ceiling-baseline-escape-continuation",
                            "status": "source-actionable",
                            "terminal": False,
                            "attempted_targets": {},
                            "protected_targets": {},
                            "post_ceiling_route_signatures": [],
                            "candidate_ids": [],
                            "continuation": None,
                        },
                        {
                            "frontier_id": "public-copy-no-route",
                            "function": "mnDiagram_DrawCellNumber",
                            "family_id": "copy-survived-pointer-reset",
                            "kind": "copy-survived-pointer-reset",
                            "status": "copy-found",
                            "terminal": False,
                            "attempted_targets": {"55": 55, "44": 44},
                            "protected_targets": {},
                            "continuation": None,
                        },
                    ],
                    "terminal_frontiers": [],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 3},
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[stale],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    assert fn["next_frontier"] is None
    reasons = {
        frontier["frontier_id"]: frontier["terminal_reason"]
        for frontier in fn["terminal_frontiers"]
    }
    assert reasons == {
        "public-empty-select-order": (
            "retained-source-select-order-repair/no-executable-target"
        ),
        "public-empty-post-ceiling": (
            "post-ceiling-continuation/no-executable-route"
        ),
        "public-copy-no-route": "copy-survived-pointer-reset/no-executable-route",
    }


def test_normalized_commandless_source_hunks_frontier_is_actionable(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "retained-frontiers.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [
                        {
                            "frontier_id": "sort-semantic-recombine",
                            "function": "mnDiagram_SortNamesByKOs",
                            "family_id": "post-ceiling-source-model-proof",
                            "kind": "post-meta-source-family-continuation-proof",
                            "status": "actionable",
                            "terminal": False,
                            "rank": 1,
                            "attempted_targets": {"34": 27, "44": 25},
                            "protected_targets": {"34": 27, "44": 25},
                            "continuation": {
                                "route": "sort-semantic-dual-target-recombine",
                                "candidate_id": "estimated-recombine",
                                "source_hunks": [
                                    {
                                        "hunk_id": "semantic-recombine",
                                        "base_start": 120,
                                        "base_end": 121,
                                        "candidate_start": 120,
                                        "candidate_end": 121,
                                        "removed": ["old;"],
                                        "added": ["new;"],
                                    }
                                ],
                            },
                        }
                    ],
                    "terminal_frontiers": [],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 1},
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["actionable"] is True
    assert next_frontier["continuation"]["route"] == (
        "sort-semantic-dual-target-recombine"
    )
    assert next_frontier["continuation"]["source_hunks"]


def test_retained_frontiers_promotes_nested_semantic_recombine_source_hunks(
    tmp_path: Path,
) -> None:
    terminal = _sort_terminal_source_model_with_actionable_nested_semantic_recombine(
        scored=True
    )
    artifact = _write_json(
        tmp_path / "sort" / "retained-frontiers.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["family_id"] == (
        "post-ceiling-source-model-proof-semantic-recombine"
    )
    assert next_frontier["continuation"]["route"] == (
        "sort-semantic-dual-target-recombine"
    )
    assert next_frontier["continuation"]["candidate_id"] == (
        "post-meta-sort-semantic-recombine-f32343df6df2"
    )
    assert next_frontier["continuation"]["source_hunks"]
    assert next_frontier["continuation"]["source_retained"] == (
        "build/diagnostics/sort/semantic-recombine-scored.c"
    )
    assert next_frontier["continuation"]["pcdump_path"] == (
        "build/diagnostics/sort/semantic-recombine-scored.pcdump.txt"
    )
    assert next_frontier["continuation"]["target_score"]["matched"] == 2
    assert next_frontier["continuation"]["target_score"].get("estimated") is False
    assert next_frontier["continuation"]["structural_guard"] == {
        "accepted": True,
        "estimated": False,
        "normalized_diff_lines": 0,
    }
    assert next_frontier["target_hits"] == {"34": True, "44": True}
    assert next_frontier["protected_hits"] == {"34": True, "44": True}

    function_payload = payload["functions"][0]
    assert any(
        row["family_id"] == "post-ceiling-source-model-proof-semantic-recombine"
        for row in function_payload["frontiers"]
    )
    assert any(
        row["frontier_id"] == terminal["frontier_id"]
        for row in function_payload["terminal_frontiers"]
    )
    assert function_payload["meta_ceiling"]["status"] == "actionable"
    assert function_payload["meta_ceiling"]["ranked_next_lanes"][0][
        "continuation"
    ]["source_hunks"]


def test_retained_frontiers_rejects_estimated_semantic_recombine_without_retained_source_proof(
    tmp_path: Path,
) -> None:
    terminal = _sort_terminal_source_model_with_actionable_nested_semantic_recombine()
    artifact = _write_json(
        tmp_path / "sort" / "retained-frontiers-estimated-recombine.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    assert payload["next_frontier"] is None
    assert not any(
        row["family_id"] == "post-ceiling-source-model-proof-semantic-recombine"
        for row in payload["functions"][0]["frontiers"]
    )


def test_retained_frontiers_source_model_metrics_use_candidate_score_hits(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "issue1069-source-model-terminal.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "status": "terminal",
            "terminal": True,
            "family_id": "post-ceiling-source-model-proof",
            "terminal_summary": {
                "status": "terminal",
                "kind": "no-post-ceiling-sort-source-family",
                "best_target_matched": 0,
                "best_target_targeted": 2,
                "target_anchors": [
                    {
                        "virtual": 34,
                        "expected": 27,
                        "actual": 27,
                        "matched": True,
                    },
                    {
                        "virtual": 44,
                        "expected": 25,
                        "actual": 22,
                        "matched": False,
                    },
                ],
                "final_force_phys": _sort_force(),
                "attempted_targets": _sort_force(),
            },
            "score_classification": {
                "candidates": _sort_issue1069_score_rows(),
            },
            "post_ceiling_source_family_discovery": {
                "retained_scored_probes": _sort_issue1069_score_rows(),
                "retained_candidate_inputs": _sort_issue1069_score_rows(),
                "exhausted_dimensions": [
                    {"dimension_id": "sort-init-indexed-write"},
                    {"dimension_id": "sort-call-return-copy-local"},
                ],
            },
            "source_model_proof": {
                "source_family_synthesis": {
                    "retained_scored_probes": _sort_issue1069_score_rows(),
                }
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    frontier = next(
        row
        for row in payload["functions"][0]["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert frontier["metrics"]["best_target_matched"] == 1
    proof = frontier["source_model_proof"]
    assert "1/2 target anchors" in proof["summary"]
    assert {
        "post-meta-source-family-sort-init-indexed-write-name-total-locals",
        "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
    } <= {row["candidate_id"] for row in proof["candidate_scores"]}
    synthesis = proof["source_family_synthesis"]
    assert {
        "post-meta-source-family-sort-init-indexed-write-name-total-locals",
        "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
    } <= {row["candidate_id"] for row in synthesis["retained_scored_probes"]}


def test_retained_frontiers_promotes_sort_post_inline_protected_continuation(
    tmp_path: Path,
) -> None:
    continuation_payload = _sort_issue1069_continuation_payload()
    artifact = _write_json(
        tmp_path / "sort" / "issue1069-protected-continuation.json",
        continuation_payload,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["family_id"] == "post-ceiling-source-model-proof"
    continuation = next_frontier["continuation"]
    assert continuation["route"] == "sort-semantic-protected-loss-repair"
    assert continuation["source_retained"].endswith(".c")
    assert continuation["pcdump_path"].endswith(".pcdump.txt")
    assert continuation["satisfied_protected_assignments"] == [
        {"ig": 44, "phys": 25}
    ]
    assert continuation["missing_protected_assignments"] == [
        {"ig": 34, "phys": 27}
    ]
    ranked = payload["functions"][0]["meta_ceiling"]["ranked_next_lanes"]
    assert ranked[0]["continuation"]["route"] == (
        "sort-semantic-protected-loss-repair"
    )


def test_common_subexpr_residual_hit_plan_validated_infers_function_and_preserves_handoff(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "plan_validated.json",
        _common_subexpr_residual_hit_payload(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    assert payload["functions"][0]["summary"]["unexhausted_count"] == 1
    next_frontier = payload["next_frontier"]
    assert next_frontier["family_id"] == "retained_gpr_common_subexpr_coalesce_source"
    assert next_frontier["attempted_targets"] == {"34": 27}
    assert next_frontier["protected_targets"] == {"44": 25}
    best = next_frontier["best_candidate"]
    assert best["source_retained"].endswith(
        "retained_gpr_common_subexpr_coalesce_source@0.c"
    )
    assert best["pcdump_path"].endswith(
        "retained_gpr_common_subexpr_coalesce_source@0.pcdump.txt"
    )
    assert best["target_score"]["matched"] == 1
    continuation = next_frontier["continuation"]
    assert continuation["route"] == "retained-common-subexpr-residual-handoff"
    assert continuation["source_retained"] == best["source_retained"]
    assert continuation["pcdump_path"] == best["pcdump_path"]
    assert continuation["target_score"] == best["target_score"]
    assert continuation["source_hunks"] == best["source_hunks"]
    assert continuation["preserved_force_phys"] == {"44": 25}
    assert continuation["protected_force_phys"] == {"44": 25}
    assert continuation["residual_force_phys"] == {"34": 27}


def test_common_subexpr_residual_handoff_consumes_protected_simplify_exhaustion(
    tmp_path: Path,
) -> None:
    plan = _write_json(
        tmp_path / "plan_validated.json",
        _common_subexpr_residual_hit_payload(),
    )
    simplify = _write_json(
        tmp_path / "simplify" / "result.json",
        _common_subexpr_residual_simplify_exhaustion(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[plan, simplify],
    )

    assert payload["status"] == "actionable"
    continuation = payload["next_frontier"]["continuation"]
    assert continuation["route"] == "retained-common-subexpr-residual-handoff"
    exhaustion = continuation["residual_simplify_exhaustion"]
    assert exhaustion["compiled"] == 40
    assert exhaustion["progress_hits"] == 0
    assert exhaustion["retained_probe_count"] == 1
    assert exhaustion["protected_force_phys"] == {"44": 25}
    assert exhaustion["residual_force_phys"] == {"34": 27}
    assert continuation["protected_force_phys"] == {"44": 25}
    assert continuation["next_force_phys"] == {"34": 27}


def test_sort_window_order_terminal_closes_common_subexpr_residual_handoff(
    tmp_path: Path,
) -> None:
    residual = _write_json(
        tmp_path / "common-subexpr" / "plan_validated.json",
        _common_subexpr_residual_hit_payload(),
    )
    terminal = _write_json(
        tmp_path / "window-order" / "select_order_plan_validated.json",
        _sort_window_order_end_pointer_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[residual, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    assert fn["next_frontier"] is None
    assert fn["summary"]["suppressed_by_terminal_count"] == 1
    common = next(
        row for row in fn["terminal_frontiers"]
        if row["family_id"] == "retained_gpr_common_subexpr_coalesce_source"
    )
    assert common["suppressed_by_terminal"] is True
    assert common["terminal_reason"] == (
        "ranked-indexed-byte-window-order-probes-exhausted"
    )
    assert str(terminal) in common["closed_by"]


def test_sort_window_order_terminal_requires_negative_score_to_close_common_subexpr(
    tmp_path: Path,
) -> None:
    terminal_payload = _sort_window_order_end_pointer_terminal()
    summary = terminal_payload["retained_case_c_window_order_continuation_summary"]
    summary["protected_negative_count"] = 0
    residual = _write_json(
        tmp_path / "common-subexpr" / "plan_validated.json",
        _common_subexpr_residual_hit_payload(),
    )
    terminal = _write_json(
        tmp_path / "window-order" / "select_order_plan_validated.json",
        terminal_payload,
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[residual, terminal],
    )

    assert payload["status"] == "actionable"
    assert payload["next_frontier"]["family_id"] == (
        "retained_gpr_common_subexpr_coalesce_source"
    )


def test_retained_meta_ceiling_replay_suppresses_closed_common_subexpr_residual(
    tmp_path: Path,
) -> None:
    residual = _write_json(
        tmp_path / "common-subexpr" / "plan_validated.json",
        _common_subexpr_residual_hit_payload(),
    )
    terminal = _write_json(
        tmp_path / "window-order" / "select_order_plan_validated.json",
        _sort_window_order_end_pointer_terminal(),
    )
    residual_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[residual],
    )
    terminal_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[terminal],
    )
    replay_payload = {
        "status": "actionable",
        "functions": [{
            "function": "mnDiagram_SortNamesByKOs",
            "frontiers": residual_payload["functions"][0]["frontiers"],
            "terminal_frontiers": (
                terminal_payload["functions"][0]["terminal_frontiers"]
            ),
            "next_frontier": residual_payload["functions"][0]["next_frontier"],
            "summary": {"unexhausted_count": 1, "terminal_count": 1},
        }],
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        replay_payload,
        function="mnDiagram_SortNamesByKOs",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []
    assert any(
        group["terminal_reason"] == (
            "ranked-indexed-byte-window-order-probes-exhausted"
        )
        for group in meta["terminal_groups"]
    )


def test_retained_meta_ceiling_promotes_nested_semantic_recombine_source_hunks_direct_call() -> None:
    meta = synthesize_retained_frontier_meta_ceiling({
        "function": "mnDiagram_SortNamesByKOs",
        "frontiers": [],
        "terminal_frontiers": [
            _sort_terminal_source_model_with_actionable_nested_semantic_recombine(
                scored=True
            )
        ],
        "next_frontier": None,
    })

    assert meta["status"] == "actionable"
    assert meta["next_frontier"]["continuation"]["route"] == (
        "sort-semantic-dual-target-recombine"
    )
    assert meta["next_frontier"]["continuation"]["source_hunks"]
    assert meta["next_frontier"]["continuation"]["source_retained"] == (
        "build/diagnostics/sort/semantic-recombine-scored.c"
    )
    assert meta["next_frontier"]["continuation"]["target_score"]["matched"] == 2
    assert (
        meta["next_frontier"]["continuation"]["target_score"].get("estimated")
        is False
    )
    assert "terminal_proof" not in meta


@pytest.mark.parametrize(
    "mutation",
    [
        "terminal-status",
        "not-accepted",
        "blocked",
        "empty-source-hunks",
    ],
)
def test_retained_frontiers_does_not_promote_terminal_or_blocked_semantic_recombine(
    tmp_path: Path,
    mutation: str,
) -> None:
    terminal = _sort_terminal_source_model_with_actionable_nested_semantic_recombine()
    semantic = terminal["source_model_proof"]["source_family_synthesis"][
        "post_ceiling_source_family_discovery"
    ]["semantic_recombine"]
    candidate = semantic["ranked_candidates"][0]
    if mutation == "terminal-status":
        semantic["status"] = "terminal"
    elif mutation == "not-accepted":
        candidate["accepted"] = False
    elif mutation == "blocked":
        candidate["blockers"] = ["recombine-overlapping-source-hunks"]
    elif mutation == "empty-source-hunks":
        candidate["source_hunks"] = []

    artifact = _write_json(
        tmp_path / "sort" / f"retained-frontiers-{mutation}.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [terminal],
                    "next_frontier": None,
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    assert payload["next_frontier"] is None
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["ranked_next_lanes"] == []


def test_retained_frontiers_protected_loss_terminal_blocks_nested_semantic_promotion(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "retained-frontiers-protected-loss.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [
                        _sort_terminal_source_model_with_actionable_nested_semantic_recombine(),
                        _sort_concrete_protected_loss_terminal(),
                    ],
                    "next_frontier": None,
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    assert payload["next_frontier"] is None
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert (
        meta["terminal_proof"]["next_unsupported_source_model"]
        == SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL
    )
    assert not any(
        row["family_id"] == "post-ceiling-source-model-proof-semantic-recombine"
        for row in payload["functions"][0]["frontiers"]
    )
    assert not any(
        row["family_id"] == "post-ceiling-source-model-proof-semantic-recombine"
        for row in meta["ranked_next_lanes"]
    )


def test_retained_frontiers_score_required_terminal_blocks_stale_nested_semantic_promotion(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "retained-frontiers-score-required.json",
        {
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [
                        _sort_terminal_source_model_with_actionable_nested_semantic_recombine(),
                        _sort_score_required_semantic_recombine_terminal(),
                    ],
                    "next_frontier": None,
                }
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    assert payload["next_frontier"] is None
    assert not any(
        row["family_id"] == "post-ceiling-source-model-proof-semantic-recombine"
        for row in payload["functions"][0]["frontiers"]
    )
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof_recombine = meta["terminal_proof"]["source_family_synthesis"][
        "post_ceiling_source_family_discovery"
    ]["semantic_recombine"]
    assert proof_recombine["status"] == "blocked"
    assert proof_recombine["ranked_candidates"][0]["recommendation"] == (
        "score-required"
    )


def test_meta_ceiling_allows_actionable_false_source_hunks_but_not_stale_command():
    source_hunk_lane = {
        "frontier_id": "sort-semantic-source-hunks",
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "actionable",
        "terminal": False,
        "actionable": False,
        "rank": 1,
        "attempted_targets": {"34": 27, "44": 25},
        "protected_targets": {"34": 27, "44": 25},
        "continuation": {
            "route": "sort-semantic-dual-target-recombine",
            "candidate_id": "estimated-recombine",
            "source_hunks": [
                {
                    "hunk_id": "semantic-recombine",
                    "base_start": 120,
                    "base_end": 121,
                    "candidate_start": 120,
                    "candidate_end": 121,
                    "removed": ["old;"],
                    "added": ["new;"],
                }
            ],
        },
    }
    stale_command_lane = {
        "frontier_id": "sort-stale-command",
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "retained-source-select-order-repair",
        "kind": "retained-source-select-order-repair",
        "status": "source-actionable",
        "terminal": False,
        "actionable": False,
        "rank": 1,
        "attempted_targets": {"34": 27, "44": 25},
        "protected_targets": {"34": 27, "44": 25},
        "continuation": {
            "route": "score-source",
            "command": (
                "melee-agent debug target score-source build/probes/sort.c "
                "--function mnDiagram_SortNamesByKOs --json"
            ),
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling({
        "function": "mnDiagram_SortNamesByKOs",
        "frontiers": [stale_command_lane, source_hunk_lane],
        "terminal_frontiers": [],
        "next_frontier": None,
        "summary": {"unexhausted_count": 2},
    })

    assert meta["status"] == "actionable"
    assert meta["next_frontier"]["frontier_id"] == "sort-semantic-source-hunks"
    assert meta["next_frontier"]["continuation"]["source_hunks"]
    assert all(
        row["frontier_id"] != "sort-stale-command"
        for row in meta["ranked_next_lanes"]
    )


def test_select_order_handoff_keeps_parent_function_when_command_is_stale(
    tmp_path: Path,
) -> None:
    handoff_payload = _draw_node_set_select_order_handoff(tmp_path)
    route = handoff_payload["case_c_order_repair"]["routes"][1]
    route["command"] = route["command"].replace(
        "-f mnDiagram_DrawCellNumber",
        "-f mnDiagram_StaleCommandFunction",
    )
    handoff = _write_json(
        tmp_path / "draw" / "node_set_split_resumed.json",
        handoff_payload,
    )
    terminal = _write_json(
        tmp_path / "draw" / "select_order.json",
        _draw_select_order_case_c_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[handoff, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["summary"]["unexhausted_count"] == 0
    assert fn["summary"]["suppressed_by_terminal_count"] == 1
    assert fn["terminal_frontiers"][0]["function"] == "mnDiagram_DrawCellNumber"

    stale_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_StaleCommandFunction"],
        artifacts=[handoff, terminal],
    )
    assert stale_payload["status"] == "no-frontiers-found"


def test_select_order_kind_summary_still_uses_generic_retained_extraction(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.c"
    artifact = _write_json(
        tmp_path / "summary.json",
        {
            "function": "fn_SelectOrderSummary",
            "retained_case_c_window_order_continuation_summary": {
                "status": "residual-hit",
                "kind": "retained-source-select-order-repair",
                "family_id": "retained_gpr_case_c_window_order_continuation",
                "attempted_targets": {"10": 3},
                "protected_targets": {"11": 4},
                "final_force_phys": {"10": 3, "11": 4},
                "best_retained_candidates": [
                    {
                        "probe_id": "same-kind-summary@0",
                        "source_retained": str(candidate),
                        "source_hunk": {
                            "strategy": "generic-retained-path",
                            "base_start": 12,
                        },
                        "classification": {
                            "classification": (
                                "residual-hit-protected-lower-drift"
                            ),
                        },
                        "target_score": {
                            "virtuals": {"10": {"matched": True}},
                            "normalized_diff_lines": 2,
                        },
                    },
                ],
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["fn_SelectOrderSummary"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert (
        next_frontier["family_id"]
        == "retained_gpr_case_c_window_order_continuation"
    )
    assert next_frontier["continuation"]["route"] == "source-hunk"
    assert next_frontier["target_hits"] == {"10": True}


def test_retained_frontiers_cli_select_order_terminal_exits_3(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: tmp_path)
    handoff = _write_json(
        tmp_path / "draw" / "node_set_split_resumed.json",
        _draw_node_set_select_order_handoff(tmp_path),
    )
    terminal = _write_json(
        tmp_path / "draw" / "select_order.json",
        _draw_select_order_case_c_terminal(),
    )

    result = CliRunner().invoke(
        search_app,
        [
            "retained-frontiers",
            "--function", "mnDiagram_DrawCellNumber",
            "--artifact", str(handoff),
            "--artifact", str(terminal),
            "--json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "all-known-frontiers-exhausted"
    assert payload["functions"][0]["summary"]["unexhausted_count"] == 0


def test_copy_survived_terminal_closes_sort_retained_frontiers(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "sort" / "stale-retained.json",
        _sort_stale_retained_frontier(),
    )
    terminal = _write_json(
        tmp_path / "sort" / "copy-terminal.json",
        _sort_copy_survived_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["next_frontier"] is None
    assert fn["frontiers"] == []
    copy = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "copy-survived-pointer-reset"
    )
    assert copy["terminal"] is True
    assert copy["terminal_reason"].startswith("copy-survived pointer-reset")
    assert copy["attempted_targets"] == {"34": 24, "41": 28}
    assert copy["metrics"]["pointer_reset_probe_count"] == 4
    stale_closed = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "retained_gpr_case_c_window_order_continuation"
    )
    assert stale_closed["suppressed_by_terminal"] is True
    assert str(terminal) in stale_closed["closed_by"]


def test_copy_survived_parent_emits_node_set_continuation(
    tmp_path: Path,
) -> None:
    parent = _write_json(
        tmp_path / "sort" / "copy-parent.json",
        _sort_copy_survived_parent(tmp_path),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[parent],
    )

    assert payload["status"] == "actionable"
    fn = payload["functions"][0]
    next_frontier = fn["next_frontier"]
    assert next_frontier["family_id"] == "copy-survived-pointer-reset"
    assert next_frontier["continuation"]["route"] == "command-hint"
    assert "debug solve node-set-split" in next_frontier["continuation"]["command"]
    assert "--var ll_probe_iter_0" in next_frontier["continuation"]["command"]
    assert fn["summary"]["unexhausted_count"] == 1


def test_node_set_exhaustion_closes_copy_survived_parent(
    tmp_path: Path,
) -> None:
    parent = _write_json(
        tmp_path / "sort" / "copy-parent.json",
        _sort_copy_survived_parent(tmp_path),
    )
    generated = _write_json(
        tmp_path / "sort" / "node-generated.json",
        _sort_generated_local_exhausted_without_target_progress(),
    )
    dst = _write_json(
        tmp_path / "sort" / "node-dst.json",
        _sort_node_set_exhausted("dst"),
    )
    loop_i = _write_json(
        tmp_path / "sort" / "node-i.json",
        _sort_node_set_exhausted("i"),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[parent, generated, dst, loop_i],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    assert fn["next_frontier"] is None
    assert fn["summary"]["unexhausted_count"] == 0
    copy = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "copy-survived-pointer-reset"
    )
    assert copy["suppressed_by_terminal"] is True
    assert copy["terminal_reason"] == (
        "copy-survived-node-set-routes-exhausted/"
        "current-source-shape-ceiling"
    )
    assert set(copy["closed_by"]) == {str(generated), str(dst), str(loop_i)}
    assert {row["var"] for row in copy["route_terminal_blockers"]} == {
        "ll_probe_iter_0",
        "dst",
        "i",
    }
    assert {
        row["terminal_reason"] for row in copy["route_terminal_blockers"]
    } == {
        "copy-survived-node-set-route-exhausted/all-wrong-register",
        "copy-survived-node-set-route-exhausted/no-target-progress",
    }


def test_copy_survived_terminal_does_not_suppress_other_function_or_unrelated_ig(
    tmp_path: Path,
) -> None:
    unrelated = _sort_stale_retained_frontier()
    summary = unrelated["retained_case_c_window_order_continuation_summary"]
    summary["attempted_targets"] = {"35": 27}
    summary["protected_targets"] = {"44": 25}
    summary["final_force_phys"] = {"35": 27, "44": 25}
    stale = _write_json(
        tmp_path / "sort" / "unrelated-retained.json",
        unrelated,
    )
    terminal = _write_json(
        tmp_path / "sort" / "copy-terminal.json",
        _sort_copy_survived_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, terminal],
    )

    assert payload["status"] == "actionable"
    fn = payload["functions"][0]
    assert fn["next_frontier"]["artifact"] == str(stale)
    assert len(fn["frontiers"]) == 1
    assert fn["frontiers"][0]["attempted_targets"] == {"35": 27}
    assert fn["frontiers"][0]["suppressed_by_terminal"] is False


def test_sort_addi_copy_product_terminal_suppresses_old_source_actionable_lane(
    tmp_path: Path,
) -> None:
    old = _write_json(
        tmp_path / "old" / "source_actionable.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "target_only_backprojection_source_probe_continuation": {
                "status": "source-actionable",
                "complete": False,
                "kind": "target-only-backprojection-source-probe-continuation",
                "pcode_lever": {
                    "dst_virtual": 34,
                    "base_virtual": 52,
                    "immediate": 28,
                },
                "attempted_targets": {"34": 27},
                "protected_targets": {"44": 25},
                "final_force_phys": _sort_force(),
                "source_file": str(tmp_path / "old" / "probe.c"),
                "resume": {"next_skip_first_candidates": 87},
            },
        },
    )
    continuation = _write_json(
        tmp_path / "terminal" / "allocator_ceiling.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "target_only_backprojection_source_probe_continuation": {
                "status": "terminal-non-source-visible",
                "complete": True,
                "kind": "target-only-backprojection-source-probe-continuation",
                "resolver_kind": (
                    "target-only-backprojection-addi-copy-product-source-resolver"
                ),
                "terminal_blocker": (
                    "addi-copy-product-operands-not-source-visible"
                ),
                "pcode_lever": {
                    "dst_virtual": 34,
                    "base_virtual": 52,
                    "immediate": 28,
                },
                "attempted_targets": {"34": 27},
                "protected_targets": {"44": 25},
                "final_force_phys": _sort_force(),
                "baseline_score": 25,
                "best_score": 266,
                "source_visible_variants": [
                    {
                        "label": "source-visible-address-owner-offset-cast",
                        "source_file": str(tmp_path / "manual.c"),
                        "score": 266,
                        "target_hits": 0,
                        "protected_preserved": False,
                    },
                ],
            },
        },
    )
    resolver = _write_json(
        tmp_path / "terminal" / "resolver.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "kind": "target-only-backprojection-addi-copy-product-source-resolver",
            "status": "terminal-non-source-visible",
            "complete": True,
            "terminal_blocker": "addi-copy-product-operands-not-source-visible",
            "pcode_lever": {
                "dst_virtual": 34,
                "base_virtual": 52,
                "immediate": 28,
            },
            "attempted_targets": {"34": 27},
            "protected_targets": {"44": 25},
            "final_force_phys": _sort_force(),
            "baseline_score": 25,
            "best_score": 266,
            "source_visible_variants": [
                {
                    "label": "source-visible-address-owner-offset-cast",
                    "source_file": str(tmp_path / "manual.c"),
                    "score": 266,
                    "target_hits": 0,
                    "protected_preserved": False,
                },
            ],
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[old, continuation, resolver],
    )

    fn = payload["functions"][0]
    assert payload["status"] == "all-known-frontiers-exhausted"
    assert fn["next_frontier"] is None
    assert fn["frontiers"] == []
    terminal = fn["terminal_frontiers"][0]
    assert set(terminal["closed_by"]) == {str(continuation), str(resolver)}
    assert terminal["terminal_reason"] == (
        "addi-copy-product-operands-not-source-visible"
    )
    assert terminal["metrics"]["baseline_score"] == 25
    assert terminal["metrics"]["best_score"] == 266
    assert terminal["metrics"]["target_hits"] == 0
    assert terminal["metrics"]["protected_preserved"] is False


def test_draw_c2_sticky_pool_terminal_suppresses_current_and_alternate_owner_lanes(
    tmp_path: Path,
) -> None:
    current = _write_json(
        tmp_path / "draw" / "current_owner.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "validation_summary": {
                "retained_case_c_target_live_range_repair_summary": {
                    "status": "blocked",
                    "kind": "retained-source-case-c-target-live-range-interference",
                    "family_id": "retained_fpr_case_c_target_live_range_repair",
                    "attempted_targets": {"37": 26},
                    "protected_targets": {"32": 26},
                    "final_force_phys": _draw_force(),
                    "evaluated_probe_count": 9,
                    "exact_count": 0,
                    "terminal_blocker": (
                        "target-aware-live-range-interference-probes-exhausted"
                    ),
                    "source_owner_terminal_spans": [
                        {
                            "source_expression": "row_offset_adj",
                            "source_owner_status": (
                                "current-source-owner-probes-exhausted"
                            ),
                        },
                    ],
                },
            },
        },
    )
    alternate = _write_json(
        tmp_path / "draw" / "alternate_owner.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "retained_case_c_target_live_range_repair_summary": {
                "status": "blocked",
                "kind": "retained-source-case-c-target-live-range-interference",
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "attempted_targets": {"37": 26},
                "protected_targets": {"32": 26},
                "final_force_phys": _draw_force(),
                "evaluated_probe_count": 12,
                "exact_count": 0,
                "terminal_blocker": "next-source-owner-exhausted",
                "source_owner_terminal_spans": [
                    {
                        "source_expression": "row_offset",
                        "source_owner_status": (
                            "current-source-owner-probes-exhausted"
                        ),
                        "next_source_owner_status": (
                            "terminal-next-source-owner-exhausted"
                        ),
                    },
                ],
            },
        },
    )
    aggregate = _write_json(
        tmp_path / "draw" / "allocator_ceiling_aggregate_plus_sticky.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "target_only_c2_sticky_pool_attribution": {
                "status": "terminal-non-source-tunable",
                "complete": True,
                "kind": "target-only-c2-sticky-pool-source-attribution",
                "terminal_blocker": (
                    "target-only-c2-sticky-pool-source-attribution-terminal"
                ),
                "target_ig": 37,
                "target_phys": 26,
                "class_id": 1,
                "final_force_phys": _draw_force(),
                "evaluated_probe_count": 42,
                "exact_count": 0,
                "protected_negative_count": 38,
                "lost_protected_count": 4,
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[current, alternate, aggregate],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["frontiers"] == []
    retained = [
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] != "target-only-c2-sticky-pool"
    ]
    assert len(retained) == 2
    assert all(str(aggregate) in frontier["closed_by"] for frontier in retained)
    c2 = next(
        frontier for frontier in fn["terminal_frontiers"]
        if frontier["family_id"] == "target-only-c2-sticky-pool"
    )
    assert c2["metrics"]["evaluated_probe_count"] == 42
    assert c2["metrics"]["exact_count"] == 0


def test_unexhausted_source_hunk_frontier_ranks_above_terminal_noise(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.c"
    actionable = _write_json(
        tmp_path / "actionable" / "simplify.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "validation_summary": {
                "retained_case_c_simplify_order_continuation_summary": {
                    "status": "residual-hit",
                    "kind": "retained-source-case-c-lower-drift-residual",
                    "family_id": "retained_gpr_case_c_simplify_order_continuation",
                    "attempted_targets": {"37": 26},
                    "protected_targets": {"32": 26},
                    "final_force_phys": _draw_force(),
                    "evaluated_probe_count": 3,
                    "exact_count": 0,
                    "best_retained_candidates": [
                        {
                            "probe_id": (
                                "retained_gpr_case_c_simplify_order_continuation@0"
                            ),
                            "source_retained": str(candidate),
                            "source_hunk": {
                                "strategy": (
                                    "case-c-max-index-probe-decl-before-dst-iter"
                                ),
                                "tag": "delete",
                                "base_start": 908,
                            },
                            "classification": {
                                "classification": (
                                    "residual-hit-protected-lower-drift"
                                ),
                            },
                            "target_score": {
                                "total": 7,
                                "matched": 2,
                                "targeted": 3,
                                "virtual_distance": 4,
                                "candidate_final_distance": 11,
                                "baseline_final_distance": 14,
                                "normalized_diff_lines": 3,
                                "virtuals": {
                                    "37": {"matched": True},
                                    "32": {"matched": True},
                                },
                            },
                        },
                    ],
                },
            },
        },
    )
    terminal = _write_json(
        tmp_path / "noise" / "terminal.json",
        {
            "function": "other_function",
            "target_only_c2_sticky_pool_attribution": {
                "status": "terminal-non-source-tunable",
                "complete": True,
                "kind": "target-only-c2-sticky-pool-source-attribution",
                "terminal_blocker": (
                    "target-only-c2-sticky-pool-source-attribution-terminal"
                ),
                "target_ig": 1,
                "target_phys": 3,
                "class_id": 1,
                "final_force_phys": {"1": 3},
                "evaluated_probe_count": 1,
                "exact_count": 0,
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[actionable, terminal],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["artifact"] == str(actionable)
    assert next_frontier["continuation"]["route"] == "source-hunk"
    assert next_frontier["continuation"]["source_hunk"]["base_start"] == 908
    assert next_frontier["target_hits"] == {"37": True}
    assert next_frontier["protected_hits"] == {"32": True}
    assert next_frontier["normalized_drift"]["normalized_diff_lines"] == 3
    assert next_frontier["normalized_drift"]["candidate_final_distance"] == 11


def test_materialized_not_scored_frontier_emits_score_source_command(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.c"
    artifact = _write_json(
        tmp_path / "unscored.json",
        {
            "function": "fn_Unscored",
            "retained_case_c_window_order_continuation_summary": {
                "status": "materialized-not-scored",
                "kind": "retained-source-case-c-implicit-address-temp",
                "family_id": "retained_gpr_case_c_window_order_continuation",
                "attempted_targets": {"34": 27},
                "protected_targets": {"44": 25},
                "best_retained_candidates": [
                    {
                        "probe_id": "retained_gpr_case_c_window_order_continuation@0",
                        "source_retained": str(candidate),
                    },
                ],
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["fn_Unscored"],
        artifacts=[artifact],
    )

    command = payload["next_frontier"]["continuation"]["command"]
    assert command == (
        "melee-agent debug target score-source "
        f"{candidate} --function fn_Unscored --json --retain-pcdump"
    )


def test_retained_frontiers_cli_accepts_multiple_functions_and_globs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: tmp_path)
    _write_json(
        tmp_path / "one" / "actionable.json",
        {
            "function": "fn_Actionable",
            "retained_case_c_simplify_order_continuation_summary": {
                "status": "residual-hit",
                "kind": "retained-source-case-c-lower-drift-residual",
                "attempted_targets": {"1": 3},
                "protected_targets": {"2": 4},
                "best_retained_candidates": [
                    {
                        "probe_id": "p0",
                        "source_retained": str(tmp_path / "candidate.c"),
                        "source_hunk": {"strategy": "move", "base_start": 10},
                        "classification": {
                            "classification": (
                                "residual-hit-protected-lower-drift"
                            ),
                        },
                    },
                ],
            },
        },
    )
    _write_json(
        tmp_path / "two" / "terminal.json",
        {
            "function": "fn_Terminal",
            "target_only_c2_sticky_pool_attribution": {
                "status": "terminal-non-source-tunable",
                "complete": True,
                "kind": "target-only-c2-sticky-pool-source-attribution",
                "terminal_blocker": (
                    "target-only-c2-sticky-pool-source-attribution-terminal"
                ),
                "target_ig": 1,
                "target_phys": 3,
                "class_id": 1,
                "final_force_phys": {"1": 3},
                "exact_count": 0,
            },
        },
    )

    result = CliRunner().invoke(
        search_app,
        [
            "retained-frontiers",
            "--function", "fn_Actionable",
            "--function", "fn_Terminal",
            "--artifact-glob", str(tmp_path / "*" / "*.json"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "actionable"
    assert [entry["function"] for entry in payload["functions"]] == [
        "fn_Actionable",
        "fn_Terminal",
    ]


def test_retained_frontiers_cli_exits_3_when_all_known_frontiers_exhausted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: tmp_path)
    terminal = _write_json(
        tmp_path / "terminal.json",
        {
            "function": "fn_Terminal",
            "target_only_c2_sticky_pool_attribution": {
                "status": "terminal-non-source-tunable",
                "complete": True,
                "kind": "target-only-c2-sticky-pool-source-attribution",
                "terminal_blocker": (
                    "target-only-c2-sticky-pool-source-attribution-terminal"
                ),
                "target_ig": 1,
                "target_phys": 3,
                "class_id": 1,
                "final_force_phys": {"1": 3},
                "exact_count": 0,
            },
        },
    )

    result = CliRunner().invoke(
        search_app,
        [
            "retained-frontiers",
            "--function", "fn_Terminal",
            "--artifact", str(terminal),
            "--json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "all-known-frontiers-exhausted"
    assert str(terminal) in payload["functions"][0]["terminal_frontiers"][0]["closed_by"]


def test_retained_frontiers_extracts_post_ceiling_baseline_escape_terminal(
    tmp_path: Path,
) -> None:
    terminal = _write_json(
        tmp_path / "baseline_escape_terminal.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "status": "terminal",
            "kind": "post-ceiling-baseline-escape",
            "evidence": {"final_force_phys": {"32": 28, "37": 26, "46": 26}},
            "terminal_summary": {
                "status": "terminal",
                "kind": "no-post-ceiling-draw-source-family",
                "terminal_blocker": "current-source-shape-ceiling",
                "terminal_reason": (
                    "no-post-ceiling-draw-source-family/"
                    "current-source-shape-ceiling"
                ),
                "candidate_count": 3,
                "scored_count": 3,
                "best_expression_matched": 0,
                "best_expression_targeted": 3,
                "best_expression_virtual_distance": 3,
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    frontier = payload["functions"][0]["terminal_frontiers"][0]
    assert frontier["family_id"] == "post-ceiling-baseline-escape"
    assert frontier["terminal_reason"] == (
        "no-post-ceiling-draw-source-family/current-source-shape-ceiling"
    )
    assert frontier["attempted_targets"] == {"32": 28, "37": 26, "46": 26}
    assert frontier["metrics"]["candidate_count"] == 3


def _draw_source_model_terminal(
    *,
    dimension_id: str,
    next_model: str,
    next_family: str | None = None,
) -> dict:
    synthesis = {
        "status": "synthesis-exhausted",
        "evidence_status": "artifact-synthesis-data",
        "attempted_equivalence_classes": [dimension_id],
        "exhausted_dimensions": [
            {"dimension_id": dimension_id, "status": "scored-terminal"}
        ],
        "candidate_count": 1,
        "scored_count": 1,
        "retained_scored_probes": [
            {
                "candidate_id": f"{dimension_id}-probe",
                "dimension_id": dimension_id,
                "target_matched": 1,
                "expression_matched": 1,
            }
        ],
        "next_unsupported_source_model": next_model,
    }
    if next_family is not None:
        synthesis["next_unsupported_source_family"] = next_family
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "terminal",
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "family_id": "post-ceiling-fpr-expression-source-model-synthesis",
        "terminal_reason": "draw-source-model-terminal",
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "attempted_targets": {"32": 28, "37": 26, "46": 26},
        "source_model_proof": {
            "register_class": "fpr",
            "attempted_equivalence_classes": [dimension_id],
            "source_family_synthesis": synthesis,
            "next_unsupported_source_model": next_model,
            **(
                {"next_unsupported_source_family": next_family}
                if next_family is not None
                else {}
            ),
        },
        "terminal_summary": {
            "status": "terminal",
            "kind": "no-post-ceiling-draw-source-family",
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": "draw-source-model-terminal",
            "candidate_count": 1,
            "scored_count": 1,
            "best_target_matched": 1,
            "best_expression_matched": 1,
            "next_unsupported_source_model": next_model,
            **(
                {"next_unsupported_source_family": next_family}
                if next_family is not None
                else {}
            ),
        },
    }


def test_retained_frontiers_prefers_draw_alternate_terminal_over_stale_coupled(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "draw-coupled-terminal.json",
        _draw_source_model_terminal(
            dimension_id=DRAW_COUPLED_LIFETIME_DIMENSION,
            next_model=DRAW_COUPLED_UNSUPPORTED_MODEL,
        ),
    )
    alternate = _write_json(
        tmp_path / "draw-alternate-terminal.json",
        _draw_source_model_terminal(
            dimension_id=DRAW_ALTERNATE_DIMENSION,
            next_model=DRAW_ALTERNATE_TERMINAL_MODEL,
            next_family=DRAW_ALTERNATE_TERMINAL_FAMILY,
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[stale, alternate],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert proof["next_unsupported_source_model"] == DRAW_ALTERNATE_TERMINAL_MODEL
    assert any(
        group.get("next_unsupported_source_family") == DRAW_ALTERNATE_TERMINAL_FAMILY
        for group in meta["terminal_groups"]
    )


def test_retained_frontiers_extracts_sort_post_ceiling_terminal(
    tmp_path: Path,
) -> None:
    terminal = _write_json(
        tmp_path / "sort_baseline_escape_terminal.json",
        _sort_post_ceiling_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    frontier = payload["functions"][0]["terminal_frontiers"][0]
    assert frontier["kind"] == "no-post-ceiling-sort-source-family"
    assert frontier["family_id"] == "post-ceiling-baseline-escape"
    assert frontier["terminal_reason"] == (
        "no-post-ceiling-sort-source-family/current-source-shape-ceiling"
    )
    assert frontier["attempted_targets"] == {"34": 27, "44": 25}
    assert frontier["metrics"]["candidate_count"] == 3


def test_inline_leverage_strict_lever_becomes_boundary_continuation(
    tmp_path: Path,
) -> None:
    post_ceiling_terminal = _write_json(
        tmp_path / "sort_baseline_escape_terminal.json",
        _sort_post_ceiling_terminal(),
    )
    leverage = _write_json(
        tmp_path / "inline_leverage.json",
        _sort_inline_leverage_strict_report(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[post_ceiling_terminal, leverage],
    )

    assert payload["status"] == "actionable"
    frontier = payload["next_frontier"]
    assert frontier["family_id"] == "inline-leverage-helper-boundary-continuation"
    assert frontier["inline_name"] == "mnDiagram_SumNameKOs"
    assert frontier["expansion_form"] == "scalar_assignment_splice"
    assert frontier["attempted_targets"] == {"34": 27, "44": 25}
    assert frontier["final_force_phys"] == {"34": 27, "44": 25}
    assert frontier["continuation"]["route"] == "inline-boundary-continuation"
    assert (
        "debug suggest inline-boundary-continuation"
        in frontier["continuation"]["command"]
    )
    assert str(leverage) in frontier["continuation"]["command"]


def test_inline_leverage_boundary_terminal_closes_strict_lever(
    tmp_path: Path,
) -> None:
    leverage = _write_json(
        tmp_path / "inline_leverage.json",
        _sort_inline_leverage_strict_report(),
    )
    terminal = _write_json(
        tmp_path / "inline_boundary_terminal.json",
        _sort_inline_boundary_terminal(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[leverage, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    frontier = payload["functions"][0]["terminal_frontiers"][0]
    assert frontier["family_id"] == "inline-leverage-helper-boundary-continuation"
    assert frontier["inline_name"] == "mnDiagram_SumNameKOs"
    assert frontier["terminal_reason"] == (
        "inline-leverage-helper-boundary-exhausted/no-ig34-ig44-progress"
    )
    exhausted = {
        row["dimension_id"] for row in frontier["exhausted_dimensions"]
    }
    assert exhausted == {
        "signature",
        "local_declarations",
        "loop_init",
        "call_argument",
        "return_local_materialization",
        "scalar_assignment_splice_boundary",
    }
    assert frontier["suppressed_by_terminal"] is True
    assert str(terminal) in frontier["closed_by"]


def test_glob_scan_skips_invalid_json_artifacts(tmp_path: Path) -> None:
    good = _write_json(
        tmp_path / "good.json",
        {
            "function": "fn_Actionable",
            "retained_case_c_simplify_order_continuation_summary": {
                "status": "residual-hit",
                "kind": "retained-source-case-c-lower-drift-residual",
                "attempted_targets": {"1": 3},
                "best_retained_candidates": [
                    {
                        "probe_id": "p0",
                        "source_retained": str(tmp_path / "candidate.c"),
                        "source_hunk": {"strategy": "move"},
                        "classification": {
                            "classification": (
                                "residual-hit-protected-lower-drift"
                            ),
                        },
                    },
                ],
            },
        },
    )
    bad = tmp_path / "empty.json"
    bad.write_text("", encoding="utf-8")

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["fn_Actionable"],
        artifact_globs=[str(tmp_path / "*.json")],
    )

    assert payload["status"] == "actionable"
    assert payload["artifact_count"] == 2
    assert payload["parsed_artifact_count"] == 1
    assert payload["next_frontier"]["artifact"] == str(good)
    assert payload["skipped_artifacts"][0]["artifact"] == str(bad.resolve())


def test_explicit_invalid_json_artifact_errors(tmp_path: Path) -> None:
    bad = tmp_path / "empty.json"
    bad.write_text("", encoding="utf-8")

    with pytest.raises(RetainedFrontierTriageError):
        triage_retained_frontiers(
            repo_root=tmp_path,
            functions=["fn_Actionable"],
            artifacts=[bad],
        )


def test_post_ceiling_baseline_escape_terminal_is_retained_frontier(
    tmp_path: Path,
) -> None:
    terminal = _write_json(
        tmp_path / "baseline_escape.json",
        {
            "function": "mnDiagram_DrawCellNumber",
            "terminal_summary": {
                "status": "terminal",
                "kind": "no-post-ceiling-draw-source-family",
                "family_id": "post-ceiling-baseline-escape",
                "suppression_family": "post-ceiling-baseline-escape",
                "terminal_blocker": "current-source-shape-ceiling",
                "terminal_reason": (
                    "no-post-ceiling-draw-source-family/"
                    "current-source-shape-ceiling"
                ),
                "candidate_count": 3,
                "scored_count": 3,
                "best_expression_matched": 0,
                "best_expression_targeted": 3,
                "best_expression_virtual_distance": 3,
                "target_anchors": [
                    {"baseline_virtual": 37, "expected": 26},
                    {"baseline_virtual": 32, "expected": 28},
                    {"baseline_virtual": 46, "expected": 26},
                ],
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    frontier = payload["functions"][0]["terminal_frontiers"][0]
    assert frontier["family_id"] == "post-ceiling-baseline-escape"
    assert frontier["suppression_family"] == "post-ceiling-baseline-escape"
    assert frontier["attempted_targets"] == {"37": 26, "32": 28, "46": 26}
    assert frontier["final_force_phys"] == {"37": 26, "32": 28, "46": 26}
    assert frontier["terminal_reason"] == (
        "no-post-ceiling-draw-source-family/current-source-shape-ceiling"
    )
    assert frontier["candidate_count"] == 3
    assert frontier["scored_count"] == 3
    assert frontier["best_expression_matched"] == 0
    assert frontier["best_expression_targeted"] == 3


def test_draw_post_meta_plateau_continuation_terminal_feeds_meta_ceiling_spans(
    tmp_path: Path,
) -> None:
    terminal = _write_json(
        tmp_path / "draw-post-meta-terminal.json",
        _draw_issue998_terminalized_continuation(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    expressions = {span.get("expression") for span in proof["source_spans"]}
    assert {
        "y_spacing * (f32) col",
        "HSD_JObjGetTranslationY(jobj2) - base",
        "fsubs f46,f45,f44",
    } <= expressions
    facts = {row["virtual"]: row for row in proof["allocator_facts"]}
    assert facts[32]["actual"] == 26
    assert facts[37]["actual"] == 28
    assert facts[46]["actual"] == 1
    assert proof["next_unsupported_source_model"] == DRAW_COUPLED_UNSUPPORTED_MODEL
    assert proof["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS


def test_source_model_residual_blockers_reads_source_model_proof_path(
    tmp_path: Path,
) -> None:
    terminal = _write_json(
        tmp_path / "draw-post-meta-terminal.json",
        _draw_issue998_terminalized_continuation(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[terminal],
    )

    frontier = next(
        row for row in payload["functions"][0]["terminal_frontiers"]
        if row.get("source_model_proof")
    )
    blockers = frontier["source_model_proof"]["residual_blocker_targets"]
    assert {row["virtual"]: row["actual"] for row in blockers} == {
        32: 26,
        37: 28,
        46: 1,
    }


def test_retained_frontiers_does_not_rank_actionable_lane_without_route() -> None:
    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_DrawCellNumber",
                    "frontiers": [_draw_issue998_route_less_plateau_frontier()],
                    "terminal_frontiers": [_draw_issue998_compat_terminal_frontier()],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 1, "terminal_count": 1},
                }
            ],
            "next_frontier": None,
        },
        function="mnDiagram_DrawCellNumber",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    assert meta["ranked_next_lanes"] == []
    assert meta["terminal_proof"]["source_spans"]
    assert (
        meta["terminal_proof"]["next_unsupported_source_model"]
        == DRAW_COUPLED_UNSUPPORTED_MODEL
    )


def test_retained_frontiers_prefers_specific_source_model_over_legacy_count() -> None:
    legacy_terminal = {
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "copy-survived-pointer-reset",
        "terminal_reason": "copy-survived-pointer-reset/no-executable-route",
        "status": "terminal",
        "terminal": True,
        "source_model_proof": {
            "next_unsupported_source_model": SORT_LEGACY_UNSUPPORTED_MODEL,
            "source_family_synthesis": {
                "exhausted_dimensions": [
                    {"dimension_id": "sort-call-return-copy-local"},
                    {"dimension_id": "sort-swap-slot-lvalue"},
                ],
            },
        },
    }
    one_hit_terminal = {
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "terminal_reason": (
            "post-meta-gpr-one-hit-source-family-continuation-exhausted/"
            "protected-structural-ceiling"
        ),
        "status": "terminal",
        "terminal": True,
        "source_model_proof": {
            "next_unsupported_source_model": SORT_ONE_HIT_UNSUPPORTED_MODEL,
            "expression_anchors": [
                {
                    "virtual": 34,
                    "expected": 27,
                    "actual": 25,
                    "baseline_source": {
                        "source_file": "src/melee/mn/mndiagram.c",
                        "source_line": 2110,
                        "name": "max_idx",
                    },
                },
            ],
            "source_family_synthesis": {
                "exhausted_dimensions": [
                    {"dimension_id": "sort-init-indexed-write"},
                    {"dimension_id": "sort-indexed-byte-cache"},
                    {"dimension_id": "sort-call-return-copy-local"},
                    {"dimension_id": "sort-swap-slot-lvalue"},
                    {"dimension_id": "sort-one-hit-structural-repair"},
                    {"dimension_id": "sort-one-hit-recombination"},
                ],
            },
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [
                        *(dict(legacy_terminal) for _ in range(16)),
                        one_hit_terminal,
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 17},
                }
            ],
            "next_frontier": None,
        },
        function="mnDiagram_SortNamesByKOs",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert (
        meta["terminal_proof"]["next_unsupported_source_model"]
        == SORT_ONE_HIT_UNSUPPORTED_MODEL
    )


def test_retained_frontiers_concrete_protected_loss_terminal_suppresses_estimated_continuation(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "sort" / "estimated_recombine.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "frontiers": [_sort_estimated_source_model_frontier()],
            "terminal_frontiers": [],
            "next_frontier": _sort_estimated_source_model_frontier(),
        },
    )
    terminal = _write_json(
        tmp_path / "sort" / "concrete_protected_loss_terminal.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "frontiers": [],
            "terminal_frontiers": [_sort_concrete_protected_loss_terminal()],
            "next_frontier": None,
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, terminal],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    suppressed = next(
        row
        for row in function_payload["terminal_frontiers"]
        if row["frontier_id"] == "sort-estimated-recombine-frontier"
    )
    assert suppressed["suppressed_by_terminal"] is True
    assert str(terminal) in suppressed["closed_by"]
    assert (
        function_payload["meta_ceiling"]["terminal_proof"][
            "next_unsupported_source_model"
        ]
        == SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL
    )


def test_retained_frontiers_next_model_prefers_concrete_protected_loss_over_estimated_source_model() -> None:
    estimated_terminal = {
        "function": "mnDiagram_SortNamesByKOs",
        "family_id": "post-ceiling-source-model-proof",
        "terminal_reason": "estimated-recombine-exhausted",
        "status": "terminal",
        "terminal": True,
        "source_model_proof": {
            "next_unsupported_source_model": SORT_ONE_HIT_UNSUPPORTED_MODEL,
            "source_family_synthesis": {
                "exhausted_dimensions": [
                    {"dimension_id": f"estimated-{index}"}
                    for index in range(20)
                ],
                "semantic_recombine": {
                    "ranked_candidates": [
                        {
                            "candidate_id": "estimated-recombine",
                            "target_score_estimate": {
                                "matched": 2,
                                "targeted": 2,
                                "estimated": True,
                            },
                        }
                    ]
                },
            },
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [
                        estimated_terminal,
                        _sort_concrete_protected_loss_terminal(),
                    ],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
            "next_frontier": None,
        },
        function="mnDiagram_SortNamesByKOs",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert (
        meta["terminal_proof"]["next_unsupported_source_model"]
        == SORT_LOWER_DRIFT_INIT_LIFETIME_MODEL
    )


def test_retained_frontiers_consumes_raw_sort_lower_drift_source_model_scores(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "sort" / "stale_lower_drift_terminal.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "frontiers": [_sort_estimated_source_model_frontier()],
            "terminal_frontiers": [_sort_concrete_protected_loss_terminal()],
            "next_frontier": None,
        },
    )
    raw = _write_json(
        tmp_path / "sort" / "source_model_from_terminal_scored.json",
        _sort_raw_lower_drift_source_model_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, raw],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    proof = function_payload["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    exhausted = {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    }
    assert "sort-protected-loss-init-lifetime" in exhausted
    assert proof["next_unsupported_source_model"] == SORT_POST_LOWER_DRIFT_MODEL
    assert "lower-drift-preserving init-lifetime variant" not in (
        proof["next_unsupported_source_model"]
    )
    assert {row["candidate_id"] for row in proof["candidate_scores"]} == {
        row["candidate_id"]
        for row in _sort_raw_lower_drift_source_model_artifact()["score_rows"]
    }


def test_retained_frontier_normalizes_raw_cross_tu_blocked_score_rows(
    tmp_path: Path,
) -> None:
    raw = _write_json(
        tmp_path / "sort" / "source_model_cross_tu_symbol_linkage.json",
        _sort_raw_cross_tu_source_model_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[raw],
    )

    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    proof = function_payload["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert SORT_CROSS_TU_DIMENSION in synthesis["attempted_equivalence_classes"]
    assert proof["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    assert proof["next_unsupported_source_family"] != SORT_CROSS_TU_DIMENSION
    retained = synthesis["retained_scored_probes"]
    assert {
        row["candidate_id"] for row in retained
    } == {
        row["candidate_id"]
        for row in _sort_raw_cross_tu_source_model_artifact()["score_rows"]
    }
    assert all("virtuals" in row["target_score"] for row in retained)
    assert {
        row["origin_dimension_id"] for row in retained
    } == {
        "sort-init-indexed-write",
        "sort-call-return-copy-local",
        "sort-indexed-byte-cache",
    }
    assert synthesis["one_hit_summary"]["best_by_target"]["34"]["candidate_id"] == (
        "post-meta-source-family-sort-init-indexed-write-name-total-locals"
    )
    assert synthesis["one_hit_summary"]["best_by_target"]["44"]["candidate_id"] in {
        "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
        "post-meta-source-family-sort-indexed-byte-cache-byte-cache",
    }


def test_retained_frontier_recognizes_sort_cross_after_whole_function_artifact(
    tmp_path: Path,
) -> None:
    raw = _write_json(
        tmp_path
        / "sort"
        / "sort_cross_after_whole_function"
        / "source_model_scored.json",
        _sort_raw_cross_tu_after_whole_function_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[raw],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert SORT_CROSS_TU_DIMENSION in synthesis["attempted_equivalence_classes"]
    assert proof["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    assert proof["next_unsupported_source_family"] != (
        "sort-unbounded-tu-data-ownership-source-context"
    )
    retained = synthesis["retained_scored_probes"]
    assert all(
        row["source_model_layer_dimension_id"] == SORT_CROSS_TU_DIMENSION
        for row in retained
    )
    scored = [row for row in retained if row.get("target_score")]
    assert scored
    assert all(row["source_retained"] for row in scored)
    assert all(row["pcdump_path"] for row in scored)
    assert all(row["source_hunks"] for row in scored)
    best = synthesis["one_hit_summary"]["best_by_target"]
    assert best["34"]["candidate_id"] == (
        "post-meta-source-family-sort-init-indexed-write-name-total-locals"
    )
    assert best["34"]["source_retained"]
    assert best["34"]["pcdump_path"]
    assert best["34"]["source_hunks"]
    assert best["34"]["target_score"]["virtuals"]["34"]["actual"] == 27
    assert best["34"]["structural_guard"]["accepted"] is False
    assert best["44"]["target_score"]["virtuals"]["44"]["actual"] == 25


def test_sort_cross_tu_no_modeled_terminal_suppresses_stale_source_model_frontier(
    tmp_path: Path,
) -> None:
    preserved = _write_json(
        tmp_path / "sort" / "sort_cross_preserved.json",
        _sort_raw_cross_tu_source_model_artifact(),
    )
    stale = _write_json(
        tmp_path / "sort" / "source_model_scored_model_only.json",
        _sort_model_only_cross_tu_blocked_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[preserved, stale],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    meta = function_payload["meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["next_frontier"] is None
    proof = meta["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert proof["next_unsupported_source_model"] == SORT_CROSS_TU_MODEL
    assert proof["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    assert SORT_CROSS_TU_DIMENSION in synthesis["attempted_equivalence_classes"]
    assert any(
        (
            row.get("reason") == SORT_CROSS_TU_NO_MODELED_BLOCKER
            or row.get("terminal_blocker") == SORT_CROSS_TU_NO_MODELED_BLOCKER
        )
        if isinstance(row, dict)
        else row == SORT_CROSS_TU_NO_MODELED_BLOCKER
        for row in synthesis["terminal_blockers"]
    )
    retained = synthesis["retained_scored_probes"]
    assert any(
        row["target_score"]["virtuals"]["34"]["matched"]
        and row["source_retained"]
        and row["pcdump_path"]
        and row["source_hunks"]
        for row in retained
    )
    assert any(
        row["target_score"]["virtuals"]["44"]["matched"]
        and row["source_retained"]
        and row["pcdump_path"]
        and row["source_hunks"]
        for row in retained
    )


def test_sort_cross_tu_no_modeled_terminal_backfills_stale_continuation_family(
    tmp_path: Path,
) -> None:
    preserved = _write_json(
        tmp_path / "sort" / "sort_cross_preserved.json",
        _sort_raw_cross_tu_source_model_artifact(),
    )
    stale = _write_json(
        tmp_path / "sort" / "source_family_continuation_stale.json",
        _sort_model_only_cross_tu_stale_continuation_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[preserved, stale],
    )

    function_payload = payload["functions"][0]
    assert function_payload["next_frontier"] is None
    proof = function_payload["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert proof["next_unsupported_source_model"] == SORT_CROSS_TU_MODEL
    assert proof["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    assert synthesis["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    assert SORT_CROSS_TU_NO_MODELED_BLOCKER in synthesis["terminal_blockers"]


def test_retained_frontier_legacy_score_rows_do_not_promote_to_cross_tu(
    tmp_path: Path,
) -> None:
    raw = _write_json(
        tmp_path / "sort" / "legacy_source_model_rows.json",
        _sort_raw_cross_tu_source_model_artifact(with_context=False),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[raw],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert SORT_CROSS_TU_DIMENSION not in synthesis["attempted_equivalence_classes"]
    assert proof.get("next_unsupported_source_family") != SORT_POST_CROSS_TU_FAMILY


def test_retained_frontier_prefers_cross_tu_terminal_over_unbounded_tu(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "sort" / "stale_unbounded_tu_terminal.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "frontiers": [],
            "terminal_frontiers": [_sort_unbounded_tu_source_model_frontier()],
            "next_frontier": None,
        },
    )
    raw = _write_json(
        tmp_path
        / "sort"
        / "sort_cross_after_whole_function"
        / "source_model_scored.json",
        _sort_raw_cross_tu_after_whole_function_artifact(),
    )
    recombine = _write_json(
        tmp_path / "sort" / "cross_tu_onehit_recombine.json",
        _sort_cross_tu_recombine_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, raw, recombine],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert SORT_CROSS_TU_DIMENSION in synthesis["attempted_equivalence_classes"]
    assert proof["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    assert proof["next_unsupported_source_family"] != SORT_CROSS_TU_DIMENSION
    assert {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    } != {"sort-unbounded-tu-data-ownership-source-context"}
    retained = synthesis["retained_scored_probes"]
    assert any(
        row["target_score"]["virtuals"]["34"]["actual"] == 27
        for row in retained
    )
    assert any(
        row["target_score"]["virtuals"]["44"]["actual"] == 25
        for row in retained
    )
    recombine_evidence = synthesis["recombine_negative_evidence"]
    assert recombine_evidence["bounded_recombine_attempted"] is True
    assert recombine_evidence["ok_combination_count"] == 3
    assert recombine_evidence["joint_preserving_combination_count"] == 0
    assert (
        "one-hit-recombine-protected-targets-not-jointly-preserved"
        in recombine_evidence["terminal_blockers"]
    )


def test_retained_frontier_prefers_post_cross_tu_terminal_over_stale_cross_tu(
    tmp_path: Path,
) -> None:
    stale_cross_tu = _write_json(
        tmp_path / "sort" / "source_model_cross_tu_symbol_linkage.json",
        _sort_raw_cross_tu_source_model_artifact(),
    )
    post_cross_tu = _write_json(
        tmp_path / "sort" / "source_model_post_cross_tu_hypothesis.json",
        _sort_post_cross_tu_source_hypothesis_terminal_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale_cross_tu, post_cross_tu],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert (
        SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION
        in synthesis["attempted_equivalence_classes"]
    )
    assert proof["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY
    )
    assert proof["next_unsupported_source_family"] != SORT_POST_CROSS_TU_FAMILY


def test_retained_frontier_prefers_post_broader_natural_inline_boundary_terminal_over_broader_natural(
    tmp_path: Path,
) -> None:
    stale_broader = _write_json(
        tmp_path / "sort" / "source_model_broader_natural.json",
        _sort_post_cross_tu_broader_natural_terminal_artifact(),
    )
    post_broader = _write_json(
        tmp_path / "sort" / "source_model_post_broader_inline_boundary.json",
        _sort_post_broader_inline_boundary_terminal_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale_broader, post_broader],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY
    )


def test_retained_frontier_keeps_broader_natural_terminal_until_post_broader_artifact_exists(
    tmp_path: Path,
) -> None:
    stale_broader = _write_json(
        tmp_path / "sort" / "source_model_broader_natural.json",
        _sort_post_cross_tu_broader_natural_terminal_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale_broader],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_FAMILY
    )


def test_retained_frontier_sort_stage_rank_does_not_upgrade_stale_terminal_by_attempted_dimension(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "sort" / "stale_selection_swap_with_post_inline_attempt.json",
        _sort_stale_selection_swap_terminal_with_post_inline_attempt(),
    )
    broader = _write_json(
        tmp_path / "sort" / "source_model_broader_natural.json",
        _sort_post_cross_tu_broader_natural_terminal_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, broader],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_FAMILY
    )
    assert proof["next_unsupported_source_family"] != (
        SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY
    )


def test_retained_frontier_sort_post_broader_still_wins_when_direct(
    tmp_path: Path,
) -> None:
    stale = _write_json(
        tmp_path / "sort" / "stale_selection_swap_with_post_inline_attempt.json",
        _sort_stale_selection_swap_terminal_with_post_inline_attempt(),
    )
    broader = _write_json(
        tmp_path / "sort" / "source_model_broader_natural.json",
        _sort_post_cross_tu_broader_natural_terminal_artifact(),
    )
    post_broader = _write_json(
        tmp_path / "sort" / "source_model_post_broader_inline_boundary.json",
        _sort_post_broader_inline_boundary_terminal_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, broader, post_broader],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY
    )


def test_retained_frontier_meta_rank_uses_explicit_sort_next_family_depth() -> None:
    stale_meta = {
        "kind": "retained-frontiers-meta-ceiling",
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal-current-source-shape-ceiling",
        "terminal_proof": {
            "next_unsupported_source_family": SORT_WHOLE_FUNCTION_DIMENSION,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": [
                    SORT_WHOLE_FUNCTION_DIMENSION,
                    SORT_HELPER_DATA_LAYOUT_FAMILY,
                    SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION,
                ],
                "exhausted_dimensions": [
                    {
                        "dimension_id": SORT_HELPER_DATA_LAYOUT_FAMILY,
                        "status": "continuation-exhausted",
                        "candidate_ids": [],
                        "candidate_count": 0,
                    },
                    {
                        "dimension_id": (
                            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION
                        ),
                        "status": "continuation-exhausted",
                        "candidate_ids": [],
                        "candidate_count": 0,
                    },
                ],
            },
        },
    }
    current_meta = {
        "kind": "retained-frontiers-meta-ceiling",
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal-current-source-shape-ceiling",
        "terminal_proof": {
            "next_unsupported_source_family": SORT_HELPER_DATA_LAYOUT_FAMILY,
            "candidate_scores": [
                {
                    "candidate_id": (
                        "post-meta-source-family-sort-whole-function-state-flow"
                    ),
                    "dimension_id": SORT_WHOLE_FUNCTION_DIMENSION,
                    "target_score": _sort_issue1069_target_score(hit_virtual="44"),
                }
            ],
            "retained_scored_probes": [
                {
                    "candidate_id": (
                        "post-meta-source-family-sort-whole-function-state-flow"
                    ),
                    "dimension_id": SORT_WHOLE_FUNCTION_DIMENSION,
                    "target_score": _sort_issue1069_target_score(hit_virtual="44"),
                }
            ],
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": [SORT_WHOLE_FUNCTION_DIMENSION],
                "exhausted_dimensions": [
                    {
                        "dimension_id": SORT_WHOLE_FUNCTION_DIMENSION,
                        "status": "scored-terminal",
                        "candidate_ids": [
                            "post-meta-source-family-sort-whole-function-state-flow"
                        ],
                        "candidate_count": 1,
                    }
                ],
                "next_unsupported_source_family": SORT_HELPER_DATA_LAYOUT_FAMILY,
            },
        },
    }

    assert retained_frontier_meta_rank(current_meta) > retained_frontier_meta_rank(
        stale_meta
    )


def test_retained_frontiers_prefers_newer_sort_terminal_over_older_deeper_terminal(
    tmp_path: Path,
) -> None:
    stale_cross_tu = _write_json(
        tmp_path / "sort" / "source_model_cross_tu_symbol_linkage.json",
        _sort_raw_cross_tu_source_model_artifact(),
    )
    current_whole_function = _write_json(
        tmp_path / "sort" / "source_model_whole_function.json",
        {
            "function": "mnDiagram_SortNamesByKOs",
            "frontiers": [],
            "terminal_frontiers": [
                _sort_source_model_terminal_artifact(
                    dimension=SORT_WHOLE_FUNCTION_DIMENSION,
                    family=SORT_HELPER_DATA_LAYOUT_FAMILY,
                    model=(
                        "Sort whole-function control/data-flow source-model "
                        "synthesis exhausted; helper/data-layout source context "
                        "is the next unsupported family."
                    ),
                    candidate_prefix="post-meta-sort-whole-function-",
                )
            ],
            "next_frontier": None,
        },
    )
    os.utime(stale_cross_tu, (1000, 1000))
    os.utime(current_whole_function, (2000, 2000))

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale_cross_tu, current_whole_function],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == SORT_HELPER_DATA_LAYOUT_FAMILY
    assert proof["next_unsupported_source_family"] != SORT_POST_CROSS_TU_FAMILY
    assert (
        proof["current_ceiling_selection"]["selected_artifact"]
        == str(current_whole_function)
    )


def test_retained_frontier_normalizes_post_broader_inline_boundary_dimension_from_candidate_prefix(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "source_model_post_broader_sparse.json",
        _sort_source_model_terminal_artifact(
            dimension="",
            family=SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY,
            model=SORT_POST_BROADER_INLINE_BOUNDARY_MODEL,
            candidate_prefix=("post-meta-sort-post-broader-natural-inline-boundary-"),
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert SORT_POST_BROADER_INLINE_BOUNDARY_DIMENSION in (
        synthesis["attempted_equivalence_classes"]
    )
    assert SORT_POST_CROSS_TU_BROADER_NATURAL_DIMENSION not in (
        synthesis["attempted_equivalence_classes"]
    )


def test_retained_frontier_prefers_post_inline_boundary_selection_emission_terminal_over_inline_boundary(
    tmp_path: Path,
) -> None:
    stale_inline = _write_json(
        tmp_path / "sort" / "source_model_post_broader_inline_boundary.json",
        _sort_post_broader_inline_boundary_terminal_artifact(),
    )
    post_inline = _write_json(
        tmp_path / "sort" / "source_model_post_inline_selection_emission.json",
        _sort_post_inline_boundary_selection_emission_terminal_artifact(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale_inline, post_inline],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY
    )


def test_retained_frontier_normalizes_post_inline_boundary_selection_emission_dimension_from_candidate_prefix(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "sort" / "source_model_post_inline_sparse.json",
        _sort_source_model_terminal_artifact(
            dimension="",
            family=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY,
            model=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_MODEL,
            candidate_prefix=(
                "post-meta-sort-post-inline-boundary-selection-emission-"
            ),
        ),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    proof = payload["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    assert SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION in (
        synthesis["attempted_equivalence_classes"]
    )
    assert SORT_POST_BROADER_INLINE_BOUNDARY_DIMENSION not in (
        synthesis["attempted_equivalence_classes"]
    )


def test_retained_frontier_cross_tu_recombine_joint_hit_stays_actionable(
    tmp_path: Path,
) -> None:
    payload = _sort_cross_tu_recombine_artifact()
    payload["combinations"][1]["target_score"]["matched"] = 2
    payload["combinations"][1]["target_score"]["virtual_distance"] = 0
    payload["combinations"][1]["target_score"]["virtuals"]["34"] = {
        "expected": 27,
        "actual": 27,
        "matched": True,
    }
    recombine = _write_json(
        tmp_path / "sort" / "cross_tu_onehit_recombine.json",
        payload,
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[recombine],
    )

    function_payload = triaged["functions"][0]
    assert triaged["status"] == "actionable"
    assert function_payload["terminal_frontiers"] == []
    next_frontier = function_payload["next_frontier"]
    assert next_frontier["actionable"] is True
    assert next_frontier["continuation"]["route"] == SORT_CROSS_TU_DIMENSION
    assert next_frontier["continuation"]["target_score"]["matched"] == 2


def test_retained_meta_ceiling_from_direct_sort_protected_loss_recombine_preserves_terminal_proof() -> None:
    meta = retained_frontier_meta_ceiling_from_payloads(
        [_sort_protected_loss_recombine_artifact()],
        function="mnDiagram_SortNamesByKOs",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    synthesis = proof["source_family_synthesis"]
    protected = synthesis["protected_structural_synthesis"]
    assert protected["required_assignments"] == _sort_force()
    assert "lower-drift-candidates-lost-protected-assignments" in (
        protected["terminal_blockers"]
    )
    assert {row["kind"] for row in protected["next_actions"]} == {
        "split-overlapping-components",
        "repair-lower-drift-protected-loss",
    }
    assert synthesis["terminal_blockers"] == protected["terminal_blockers"]
    assert {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    } == {"sort-protected-loss-init-lifetime"}
    assert synthesis["ranked_candidates"][0]["source_hunks"]
    assert synthesis["candidate_scores"][0]["source_hunks"]
    assert (
        proof["next_unsupported_source_model"]
        == SORT_POST_LOWER_DRIFT_MODEL
    )


def test_retained_frontiers_source_model_proof_merge_prefers_newer_lower_drift_exhaustion() -> None:
    older = _sort_concrete_protected_loss_terminal()
    newer = {
        **_sort_concrete_protected_loss_terminal(),
        "frontier_id": "sort-lower-drift-terminal",
        "source_model_proof": {
            "next_unsupported_source_model": SORT_POST_LOWER_DRIFT_MODEL,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "evidence_status": "artifact-score-rows",
                "exhausted_dimensions": [
                    {"dimension_id": "sort-protected-loss-init-lifetime"}
                ],
            },
            "candidate_scores": [
                {
                    "candidate_id": "post-meta-source-family-sort-protected-loss",
                    "dimension_id": "sort-protected-loss-init-lifetime",
                }
            ],
        },
    }

    meta = synthesize_retained_frontier_meta_ceiling(
        {
            "status": "all-known-frontiers-exhausted",
            "functions": [
                {
                    "function": "mnDiagram_SortNamesByKOs",
                    "frontiers": [],
                    "terminal_frontiers": [older, newer],
                    "next_frontier": None,
                    "summary": {"unexhausted_count": 0, "terminal_count": 2},
                }
            ],
        },
        function="mnDiagram_SortNamesByKOs",
    )

    assert meta["status"] == "terminal-current-source-shape-ceiling"
    proof = meta["terminal_proof"]
    assert proof["next_unsupported_source_model"] == SORT_POST_LOWER_DRIFT_MODEL
    assert {
        row["dimension_id"]
        for row in proof["source_family_synthesis"]["exhausted_dimensions"]
    } == {"sort-protected-loss-init-lifetime"}


def _inline_local_write_terminal_payload(function: str = "mnDiagram_DrawCellNumber") -> dict:
    score_row = {
        "candidate_id": "local-write-0001",
        "family": "inline-local-write-helper",
        "strategy": "block-macro",
        "source_model_layer_dimension_id": "inline-local-write-helper",
        "dimension_id": "inline-local-write-helper-block-macro",
        "source_retained": "build/diagnostics/local-write-0001.c",
        "pcdump_path": "build/diagnostics/local-write-0001.pcdump.txt",
        "source_hunks": [{"hunk_id": "h001"}],
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": "f28", "actual": "f31", "matched": False},
                "37": {"expected": "f26", "actual": "f29", "matched": False},
                "46": {"expected": "f26", "actual": "f30", "matched": False},
            },
        },
        "expression_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": "f28", "actual": "f31", "matched": False},
                "37": {"expected": "f26", "actual": "f29", "matched": False},
                "46": {"expected": "f26", "actual": "f30", "matched": False},
            },
        },
        "structural_guard": {"accepted": True},
        "target_matched": 0,
        "target_targeted": 3,
        "target_virtual_distance": 3,
        "expression_matched": 0,
        "expression_targeted": 3,
        "expression_virtual_distance": 3,
        "terminal_safe": True,
    }
    terminal_reason = (
        "inline-local-write-helper-family-exhausted/"
        "no-target-or-expression-improvement"
    )
    synthesis = {
        "status": "synthesis-exhausted",
        "evidence_status": "artifact-score-rows",
        "attempted_equivalence_classes": [
            "inline-local-write-helper",
            "inline-local-write-helper-block-macro",
        ],
        "exhausted_dimensions": [
            {
                "dimension_id": "inline-local-write-helper",
                "status": "terminal",
                "exhaustion_reason": terminal_reason,
            }
        ],
        "scored_candidate_ids": ["local-write-0001"],
        "all_candidate_ids": ["local-write-0001"],
        "candidate_count": 1,
        "retained_scored_probes": [score_row],
    }
    return {
        "function": function,
        "status": "terminal",
        "terminal": True,
        "kind": "inline-local-write-source-shape-exhausted",
        "family_id": "post-ceiling-source-model-proof",
        "terminal_reason": terminal_reason,
        "terminal_summary": {
            "kind": "no-post-ceiling-source-family",
            "candidate_count": 1,
            "scored_count": 1,
            "best_candidate_id": "local-write-0001",
            "best_target_matched": 0,
            "best_target_targeted": 3,
            "best_expression_matched": 0,
            "best_expression_targeted": 3,
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": terminal_reason,
        },
        "score_rows": [score_row],
        "source_model_proof": {
            "kind": "inline-local-write-source-shape-exhausted",
            "status": "terminal",
            "terminal_reason": terminal_reason,
            "candidate_scores": [score_row],
            "retained_scored_probes": [score_row],
            "attempted_equivalence_classes": [
                "inline-local-write-helper",
                "inline-local-write-helper-block-macro",
            ],
            "exhausted_dimensions": synthesis["exhausted_dimensions"],
            "source_family_synthesis": synthesis,
        },
    }


def test_retained_frontiers_consumes_suggest_inlines_local_write_terminal_proof(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "suggest_inlines_local_write_terminal.json",
        _inline_local_write_terminal_payload(),
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    assert payload["status"] == "all-known-frontiers-exhausted"
    fn = payload["functions"][0]
    assert fn["meta_ceiling"]["status"] == "terminal-current-source-shape-ceiling"
    proof = fn["meta_ceiling"]["terminal_proof"]
    candidate = proof["candidate_scores"][0]
    assert candidate["source_retained"] == "build/diagnostics/local-write-0001.c"
    assert candidate["pcdump_path"] == (
        "build/diagnostics/local-write-0001.pcdump.txt"
    )


def test_retained_frontiers_does_not_terminalize_loose_score_source_json(
    tmp_path: Path,
) -> None:
    artifact = _write_json(
        tmp_path / "loose_score_source.json",
        {
            "score": 3,
            "target_score": {"matched": 0, "targeted": 3},
            "expression_score": {"matched": 0, "targeted": 3},
            "pcdump_path": "build/diagnostics/loose.pcdump.txt",
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    assert payload["status"] == "no-frontiers-found"


@pytest.mark.parametrize(
    ("candidate_id", "dimension_id"),
    [
        (
            "post-meta-source-family-sort-swap-slot-lvalue-byte-temp",
            "sort-swap-slot-lvalue",
        ),
        (
            "post-meta-sort-semantic-recombine-abc123",
            "sort-semantic-dual-target-recombine",
        ),
    ],
)
def test_retained_frontiers_adapts_scoped_direct_sort_score_source_json(
    tmp_path: Path,
    candidate_id: str,
    dimension_id: str,
) -> None:
    source = f"build/diagnostics/{candidate_id}.c"
    artifact = _write_json(
        tmp_path / f"{candidate_id}.json",
        {
            "score": 4,
            "function": "mnDiagram_SortNamesByKOs",
            "score_function": "mnDiagram_SortNamesByKOs",
            "source_file": source,
            "source_retained": source,
            "c_file": source,
            "cflags_from": "src/melee/mn/mndiagram.c",
            "candidate_id": candidate_id,
            "full_unit_source": True,
            "pcdump_path": source.replace(".c", ".pcdump.txt"),
            "target_score": {
                "matched": 1,
                "targeted": 2,
                "virtual_distance": 1,
                "virtuals": {
                    "34": {"expected": 27, "actual": 27, "matched": True},
                    "44": {"expected": 25, "actual": 22, "matched": False},
                },
            },
        },
    )

    payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[artifact],
    )

    assert payload["status"] == "actionable"
    next_frontier = payload["next_frontier"]
    assert next_frontier["terminal"] is False
    assert next_frontier["dimension_id"] == dimension_id
    assert next_frontier["candidate_id"] == candidate_id
    assert next_frontier["continuation"]["route"] == "score-source"
    assert next_frontier["continuation"]["source_retained"] == source
    assert "debug target score-source" in next_frontier["continuation"]["command"]
    meta = payload["functions"][0]["meta_ceiling"]
    assert meta["status"] == "actionable"
    assert meta["next_frontier"]["dimension_id"] == dimension_id
