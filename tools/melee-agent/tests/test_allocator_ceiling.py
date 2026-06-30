import json
import os
import textwrap

import pytest
from typer.testing import CliRunner

from src.cli import debug as cli_debug
from src.mwcc_debug.allocator_ceiling import (
    EvidenceFormatError,
    EvidenceFunctionMismatch,
    classify_allocator_ceiling,
    flatten_evidence_items,
    render_allocator_ceiling_text,
)
from src.mwcc_debug.retained_frontier_triage import triage_retained_frontiers

DRAW_COUPLED_UNSUPPORTED_CLASS = "draw-coupled-post-meta-fpr-expression-lifetime"
DRAW_COUPLED_UNSUPPORTED_MODEL = (
    "Draw coupled post-meta FPR expression lifetime/materialization across "
    "col_offset product, row_offset fsubs, and digit-animation fsubs/callarg temp."
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
SORT_POST_LOWER_DRIFT_MODEL = (
    "Sort protected-loss init-lifetime scoring exhausted the bounded lower-drift "
    "source family without jointly preserving IG34/IG44. The next unsupported "
    "source model is the full Sort selection/swap source structure outside the "
    "current protected-loss and init-lifetime families."
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
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-split"
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
DRAW_HELPER_BOUNDARY_REJECTION_REASON = (
    "span writes locals; void-helper extraction would need output params"
)


def _sort_force():
    return {"34": 27, "44": 25}


def _solve_delta(function="fn_test"):
    return {
        "function": function,
        "class_id": 0,
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": function,
            "blocker": "structurally-different-virtual",
            "missing_virtuals": [{"target_ig": 40}],
        },
    }


def _bare_delta(function="fn_test"):
    return {
        "kind": "node-set-delta",
        "function": function,
        "blocker": "structurally-different-virtual",
        "missing_virtuals": [{"target_ig": 40}],
    }


def _force_match(function="fn_test"):
    return {
        "function": function,
        "force_vector_verify": {
            "ran": True,
            "union": {"status": "match", "returncode": 0},
        },
    }


def _node_wrong(function="fn_test"):
    return {
        "function": function,
        "status": "exhausted",
        "wrong_register_exhausted": True,
        "objective_counts": {"wrong-register": 6},
        "exhaustive": True,
    }


def _target_only_backprojection_input(
    tmp_path,
    *,
    function="fn_test",
    class_id=0,
    target_ig=40,
    desired_phys=25,
    natural_phys=29,
    forced_phys=25,
    blocker_ig=50,
    include_forced=True,
):
    # The hook parser's compact decision-row regex uses rN for the register
    # token even when the section class is FPR; class-specific display happens
    # after parsing.
    prefix = "r"
    natural = tmp_path / "natural.pcdump.txt"
    forced = tmp_path / "forced.pcdump.txt"
    natural.write_text(textwrap.dedent(f"""\
        Starting function {function}
        SIMPLIFY GRAPH (class={class_id}, n_colors=32, n_class_regs=32)
        iter ig_idx degree arraySize flags
        0 {blocker_ig} 0 0 0x0
        1 {target_ig} 1 1 0x0
        COLORGRAPH DECISIONS (class={class_id}, result=0, n_nodes=2)
        iter ig_idx reg degree n_interferers flags
        0 {blocker_ig} {prefix}{desired_phys} 0 0 0x0
        1 {target_ig} {prefix}{natural_phys} 1 1 0x0
          interferers: {blocker_ig}=r{desired_phys}
    """))
    forced.write_text(textwrap.dedent(f"""\
        Starting function {function}
        SIMPLIFY GRAPH (class={class_id}, n_colors=32, n_class_regs=32)
        iter ig_idx degree arraySize flags
        0 {blocker_ig} 0 0 0x0
        1 {target_ig} 1 1 0x0
        COLORGRAPH DECISIONS (class={class_id}, result=0, n_nodes=2)
        iter ig_idx reg degree n_interferers flags
        0 {blocker_ig} {prefix}{natural_phys} 0 0 0x0
        1 {target_ig} {prefix}{forced_phys} 1 1 0x0
          interferers: {blocker_ig}=r{natural_phys}
    """))
    payload = {
        "function": function,
        "kind": "target-only-allocator-backprojection-input",
        "natural_pcdump": str(natural),
    }
    if include_forced:
        payload["forced_pcdump"] = str(forced)
    return payload


def _draw_delta(function="mnDiagram_DrawCellNumber"):
    return {
        "kind": "node-set-delta",
        "function": function,
        "class_id": 1,
        "blocker": "structurally-different-virtual",
        "missing_virtuals": [
            {
                "target_ig": 32,
                "current_register": "f30",
                "desired_registers": ["f28"],
                "source": {
                    "kind": "local",
                    "name": "col_offset",
                    "expression": "col_offset",
                },
            },
            {
                "target_ig": 37,
                "current_register": "f31",
                "desired_registers": ["f26"],
                "source": {
                    "kind": "local",
                    "name": "row_offset",
                    "expression": "row_offset",
                },
            },
            {
                "target_ig": 46,
                "current_register": "f29",
                "desired_registers": ["f26"],
                "source": {
                    "kind": "fpr-temp",
                    "expression": "fsubs",
                    "confidence": "pcode-first-def",
                    "pcode_first_def": {
                        "opcode": "fsubs",
                        "operands": ["f1", "f2", "f3"],
                    },
                },
            },
        ],
    }


def _draw_node_wrong(target_ig, function="mnDiagram_DrawCellNumber"):
    return {
        "function": function,
        "status": "exhausted",
        "exhaustive": True,
        "stop_reason": None,
        "generated_count": 4,
        "scored_count": 4,
        "evaluated_count": 4,
        "pending_count": 0,
        "realized_count": 0,
        "objective_counts": {"wrong-register": 4},
        "request": {
            "function": function,
            "class_id": 1,
            "target_ig": target_ig,
            "target_reg": "f28" if target_ig == 32 else "f26",
        },
    }


def _draw_coupled_node_summary(
    *,
    function="mnDiagram_DrawCellNumber",
    stop_kind=None,
):
    summary = {
        "function": function,
        "status": "exhausted",
        "exhaustive": stop_kind is None,
        "generated_count": 8,
        "scored_count": 8,
        "evaluated_count": 8,
        "pending_count": 0 if stop_kind is None else 3,
        "realized_count": 0,
        "objective_counts": {"wrong-register": 8},
        "coupled_requests": [
            {"function": function, "class_id": 1, "target_ig": 32, "target_reg": "f28"},
            {"function": function, "class_id": 1, "target_ig": 37, "target_reg": "f26"},
        ],
    }
    if stop_kind is not None:
        summary["stop_reason"] = stop_kind
        summary["stop_condition"] = {
            "kind": stop_kind,
            "resume_command": "melee-agent debug solve node-set-split --resume-summary draw.json",
        }
    return summary


def _draw_select_order_terminal(function="mnDiagram_DrawCellNumber"):
    return {
        "function": function,
        "terminal_exhaustion_summary": {
            "status": "blocked",
            "kind": "degree-zero-fpr-case-c-source-exhaustion",
            "force_phys_targets": {"32": 28, "37": 26, "46": 26},
            "diagnostic_bucket_counts": {"degree-zero": 3},
            "best_retained_variants": [],
            "next_source_lever_classes": [],
            "terminal_blocker": "transform-family-exhausted",
        },
    }


def _draw_force_vector_payload(
    tmp_path,
    *,
    function="mnDiagram_DrawCellNumber",
    union_status="match",
    ran=True,
):
    natural = tmp_path / "draw-natural.pcdump.txt"
    forced = tmp_path / "draw-forced.pcdump.txt"
    natural.write_text(textwrap.dedent(f"""\
        Starting function {function}
        SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=32)
        iter ig_idx degree arraySize flags
        0 60 0 0 0x0
        1 32 1 1 0x0
        2 37 0 0 0x0
        3 46 0 0 0x0
        COLORGRAPH DECISIONS (class=1, result=0, n_nodes=4)
        iter ig_idx reg degree n_interferers flags
        0 60 r28 0 0 0x0
        1 32 r30 1 1 0x0
          interferers: 60=r28
        2 37 r28 0 0 0x0
        3 46 r29 0 0 0x0
    """), encoding="utf-8")
    forced.write_text(textwrap.dedent(f"""\
        Starting function {function}
        SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=32)
        iter ig_idx degree arraySize flags
        0 60 0 0 0x0
        1 32 1 1 0x0
        2 37 0 0 0x0
        3 46 0 0 0x0
        COLORGRAPH DECISIONS (class=1, result=0, n_nodes=4)
        iter ig_idx reg degree n_interferers flags
        0 60 r30 0 0 0x0
        1 32 r28 1 1 0x0
          interferers: 60=r30
        2 37 r26 0 0 0x0
        3 46 r26 0 0 0x0
    """), encoding="utf-8")
    return {
        "function": function,
        "force_phys": {"32": 28, "37": 26, "46": 26},
        "force_vector": (
            "class1:ig32:phys=f28,"
            "class1:ig37:phys=f26,"
            "class1:ig46:phys=f26"
        ),
        "natural_pcdump": str(natural),
        "force_vector_verify": {
            "ran": ran,
            "union": {
                "status": union_status,
                "pcdump": str(forced),
            },
        },
    }


def _node_wrong_missing_target_exhausted(function="fn_test"):
    return {
        "function": function,
        "status": "exhausted",
        "exhaustive": True,
        "stop_reason": None,
        "generated_count": 8,
        "scored_count": 8,
        "evaluated_count": 8,
        "pending_count": 0,
        "realized_count": 0,
        "objective_counts": {
            "wrong-register": 7,
            "missing-target": 1,
        },
    }


def _transform_negative(function="fn_test"):
    return {
        "function": function,
        "validation_summary": {
            "stop_condition": "exhausted-negative-evidence",
            "evaluated_probes": 6,
            "remaining_probe_ids": [],
            "outcomes": {"negative-evidence": 6},
        },
        "node_set_delta_summary": {
            "provided": True,
            "missing_count": 3,
            "bindable_count": 2,
            "skipped_count": 1,
            "omitted_count": 0,
        },
    }


def _retained_frontiers_function_entry(
    function="fn_test",
    *,
    terminal=True,
    actionable=False,
):
    terminal_frontiers = [
        {
            "function": function,
            "frontier_id": f"{function}|post-ceiling-source-model-proof|fixture",
            "family_id": "post-ceiling-source-model-proof",
            "kind": "post-ceiling-gpr-case-c-source-model-synthesis-proof",
            "status": "terminal",
            "terminal": True,
            "terminal_reason": (
                "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
            ),
            "suppression_family": "post-ceiling-source-model-proof",
            "attempted_targets": {"34": 27, "44": 25},
            "source_model_proof": {
                "target_anchors": [
                    {"virtual": 34, "expected": 27, "actual": None},
                    {"virtual": 44, "expected": 25, "actual": None},
                ],
                "candidate_scores": [
                    {
                        "candidate_id": "fixture-sort-source-model",
                        "wrong_registers": [
                            {"virtual": 34, "expected": 27, "actual": 24},
                            {"virtual": 44, "expected": 25, "actual": 27},
                        ],
                    }
                ],
                "next_unsupported_source_model": "fixture unsupported model",
            },
        }
    ] if terminal else []
    frontiers = []
    next_frontier = None
    if actionable:
        next_frontier = {
            "function": function,
            "frontier_id": f"{function}|retained-source-select-order-repair|fixture",
            "family_id": "retained-source-select-order-repair",
            "status": "source-actionable",
            "terminal": False,
            "actionable": True,
            "rank": 1,
            "attempted_targets": {"34": 27},
            "protected_targets": {"44": 25},
            "final_force_phys": {"34": 27, "44": 25},
            "continuation": {
                "route": "command-hint",
                "command": (
                    "melee-agent debug target score-source build/probes/fn_test.c "
                    "--function fn_test --json"
                ),
            },
        }
        frontiers = [next_frontier]
    return {
        "function": function,
        "frontiers": frontiers,
        "terminal_frontiers": terminal_frontiers,
        "next_frontier": next_frontier,
        "summary": {
            "unexhausted_count": len(frontiers),
            "terminal_count": len(terminal_frontiers),
            "suppressed_by_terminal_count": 0,
        },
    }


def _retained_frontiers_aggregate(
    function="fn_test",
    *,
    terminal=True,
    actionable=False,
):
    entry = _retained_frontiers_function_entry(
        function,
        terminal=terminal,
        actionable=actionable,
    )
    return {
        "status": "actionable" if actionable else (
            "all-known-frontiers-exhausted" if terminal else "no-frontiers-found"
        ),
        "artifact_count": 1,
        "parsed_artifact_count": 1,
        "skipped_artifacts": [],
        "functions": [entry],
        "next_frontier": entry["next_frontier"],
    }


def _draw_issue998_retained_frontiers_aggregate():
    force = {"32": 28, "37": 26, "46": 26}
    expression_anchors = [
        {
            "virtual": 32,
            "baseline_virtual": 32,
            "name": "col_offset",
            "expression": "y_spacing * (f32) col",
            "expected": 28,
            "actual": 26,
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
            "baseline_source": {
                "source_file": "src/melee/mn/mndiagram.c",
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
        },
    ]
    terminal = {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "mnDiagram_DrawCellNumber|post-ceiling-source-model-proof|998",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": "post-ceiling-fpr-expression-source-model-synthesis-exhausted",
        "suppression_family": "post-ceiling-source-model-proof",
        "attempted_targets": force,
        "final_force_phys": force,
        "source_model_proof": {
            "register_class": "fpr",
            "expression_anchors": expression_anchors,
            "residual_blocker_targets": [
                {"virtual": 32, "expected": 28, "actual": 26},
                {"virtual": 37, "expected": 26, "actual": 28},
                {"virtual": 46, "expected": 26, "actual": 1},
            ],
            "source_family_synthesis": {
                "exhausted_dimensions": [
                    {"dimension_id": "draw-col-cast-product-local"},
                    {"dimension_id": "draw-row-translation-scale-split"},
                    {"dimension_id": "draw-digit-callarg-fsubs-temp"},
                ],
                "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
            },
            "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
            "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
        },
    }
    return {
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
        "next_frontier": None,
    }


def _draw_issue1040_post_whole_terminal_discovery():
    retained_row = {
        "candidate_id": (
            "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
        ),
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "target_score": {"matched": 1, "targeted": 3, "virtual_distance": 2},
        "expression_score": {"matched": 1, "targeted": 3, "virtual_distance": 2},
        "structural_guard": {
            "accepted": False,
            "reason": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 11,
            "opcode_similarity": 0.955684,
        },
        "source_hunks": [{"variant_id": "joint-data-owner-with-loop-object"}],
        "pcdump_path": "build/draw/post-whole.pcdump.txt",
    }
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "unsupported-source-family",
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "terminal_reason": (
            "post-source-context-next-dimension/unsupported-source-family"
        ),
        "trigger_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "exhausted_source_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "exhausted_dimensions": [DRAW_POST_SOURCE_CONTEXT_DIMENSION],
        "next_unsupported_source_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
        "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        "retained_evidence": [retained_row],
        "ranked_retained_c_probes": [retained_row],
        "source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "function": "mnDiagram_DrawCellNumber",
                "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            }
        ],
    }


def _draw_stale_post_source_context_actionable_discovery():
    return {
        "function": "mnDiagram_DrawCellNumber",
        "status": "source-actionable",
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "next_frontier": {
            "function": "mnDiagram_DrawCellNumber",
            "frontier_id": "draw-stale-post-source-context",
            "family_id": "post-source-context-fpr-ceiling-next-dimension",
            "kind": "post-source-context-fpr-next-dimension-discovery",
            "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            "continuation": {
                "route": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
                "source_hunks": [{"hunk_id": "stale-handoff"}],
            },
        },
    }


def _draw_post_all_known_lane():
    return {
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


def _draw_post_all_known_terminal():
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-post-all-known-terminal",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "draw-post-all-known-frontiers-source-context-hypothesis-"
            "exhausted/no-floor-improvement"
        ),
        "suppression_family": "post-ceiling-source-model-proof",
        "attempted_targets": {"32": 28, "37": 26, "46": 26},
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "source_model_proof": {
            "register_class": "fpr",
            "attempted_equivalence_classes": [DRAW_POST_ALL_KNOWN_DIMENSION],
            "exhausted_source_dimension": DRAW_POST_ALL_KNOWN_DIMENSION,
            "exhausted_dimensions": [
                {"dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION}
            ],
            "candidate_scores": [
                {
                    "candidate_id": "draw-post-all-known-terminal-probe",
                    "dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION,
                    "target_score": {"matched": 1, "targeted": 3},
                    "expression_score": {"matched": 1, "targeted": 3},
                }
            ],
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "evidence_status": "artifact-synthesis-data",
                "attempted_equivalence_classes": [DRAW_POST_ALL_KNOWN_DIMENSION],
                "exhausted_dimensions": [
                    {"dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION}
                ],
                "retained_scored_probes": [
                    {
                        "candidate_id": "draw-post-all-known-terminal-probe",
                        "dimension_id": DRAW_POST_ALL_KNOWN_DIMENSION,
                    }
                ],
                "next_unsupported_source_family": DRAW_POST_ALL_KNOWN_FINAL_FAMILY,
                "next_unsupported_source_model": DRAW_POST_ALL_KNOWN_FINAL_MODEL,
            },
            "next_unsupported_source_family": DRAW_POST_ALL_KNOWN_FINAL_FAMILY,
            "next_unsupported_source_model": DRAW_POST_ALL_KNOWN_FINAL_MODEL,
        },
    }


def _draw_post_all_known_retained_frontiers_aggregate(*, actionable=False):
    lane = _draw_post_all_known_lane() if actionable else None
    terminal = _draw_post_all_known_terminal() if not actionable else None
    frontiers = [lane] if lane is not None else []
    terminal_frontiers = [terminal] if terminal is not None else []
    return {
        "status": "actionable" if actionable else "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": frontiers,
                "terminal_frontiers": terminal_frontiers,
                "next_frontier": lane,
                "summary": {
                    "unexhausted_count": len(frontiers),
                    "terminal_count": len(terminal_frontiers),
                },
            }
        ],
        "next_frontier": lane,
    }


def _draw_product_translate_lane():
    lane = _draw_post_all_known_lane()
    lane["frontier_id"] = "draw-product-translate-candidate"
    lane["candidate_id"] = "draw-post-all-known-product-translate-graph-candidate"
    lane["dimension_id"] = DRAW_PRODUCT_TRANSLATE_DIMENSION
    lane["source_model_proof"] = {
        "attempted_equivalence_classes": [DRAW_PRODUCT_TRANSLATE_DIMENSION],
        "source_family_synthesis": {
            "evidence_status": "artifact-score-rows",
            "exhausted_dimensions": [
                {"dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION}
            ],
        },
    }
    lane["continuation"] = {
        "route": DRAW_PRODUCT_TRANSLATE_DIMENSION,
        "candidate_id": "draw-post-all-known-product-translate-graph-candidate",
        "source_hunks": [{"hunk_id": "product-translate"}],
        "pcdump_path": "build/product-translate.pcdump.txt",
    }
    return lane


def _draw_product_translate_terminal():
    terminal = _draw_post_all_known_terminal()
    terminal["frontier_id"] = "draw-product-translate-terminal"
    terminal["terminal_reason"] = (
        "draw-post-all-known-loop-product-translate-expression-graph-"
        "exhausted/no-floor-improvement"
    )
    proof = terminal["source_model_proof"]
    proof["attempted_equivalence_classes"] = [DRAW_PRODUCT_TRANSLATE_DIMENSION]
    proof["exhausted_source_dimension"] = DRAW_PRODUCT_TRANSLATE_DIMENSION
    proof["exhausted_dimensions"] = [
        {"dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION}
    ]
    proof["candidate_scores"] = [
        {
            "candidate_id": "draw-post-all-known-product-translate-graph-terminal",
            "dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION,
            "target_score": {"matched": 1, "targeted": 3},
            "expression_score": {"matched": 1, "targeted": 3},
        }
    ]
    synthesis = proof["source_family_synthesis"]
    synthesis["attempted_equivalence_classes"] = [DRAW_PRODUCT_TRANSLATE_DIMENSION]
    synthesis["exhausted_dimensions"] = [
        {"dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION}
    ]
    synthesis["retained_scored_probes"] = [
        {
            "candidate_id": "draw-post-all-known-product-translate-graph-terminal",
            "dimension_id": DRAW_PRODUCT_TRANSLATE_DIMENSION,
            "pcdump_path": "build/product-translate.pcdump.txt",
        }
    ]
    synthesis["next_unsupported_source_family"] = DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY
    synthesis["next_unsupported_source_model"] = DRAW_PRODUCT_TRANSLATE_FINAL_MODEL
    proof["next_unsupported_source_family"] = DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY
    proof["next_unsupported_source_model"] = DRAW_PRODUCT_TRANSLATE_FINAL_MODEL
    return terminal


def _draw_product_translate_retained_frontiers_aggregate(*, actionable=False):
    stale = _draw_post_all_known_lane()
    lane = _draw_product_translate_lane() if actionable else None
    terminal = _draw_product_translate_terminal() if not actionable else None
    frontiers = [stale, lane] if lane is not None else []
    terminal_frontiers = [terminal] if terminal is not None else []
    return {
        "status": "actionable" if actionable else "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": frontiers,
                "terminal_frontiers": terminal_frontiers,
                "next_frontier": stale if actionable else None,
                "summary": {
                    "unexhausted_count": len(frontiers),
                    "terminal_count": len(terminal_frontiers),
                },
            }
        ],
        "next_frontier": lane if actionable else None,
    }


def _draw_stack_clean_no_anchor_evidence():
    return {
        "seed_candidate_id": (
            "draw-post-all-known-product-translate-graph-"
            "col-product-before-row-delta-with-y-offset"
        ),
        "source_retained": "build/stack-clean-seed.c",
        "pcdump_path": "build/stack-clean-seed.pcdump.txt",
        "source_hunks": [{"hunk_id": "stack-clean-seed"}],
        "target_score": {"matched": 0, "targeted": 3, "virtual_distance": 3},
        "expression_score": {"matched": 0, "targeted": 3, "virtual_distance": 3},
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
    }


def _draw_stack_clean_no_anchor_lane():
    evidence = _draw_stack_clean_no_anchor_evidence()
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-stack-clean-no-anchor-candidate",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "terminal": False,
        "actionable": True,
        "candidate_id": evidence["seed_candidate_id"],
        "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "source_model_layer_dimension_id": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "continuation": {
            "route": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "seed_candidate_id": evidence["seed_candidate_id"],
            "candidate_id": evidence["seed_candidate_id"],
            "source_retained": evidence["source_retained"],
            "pcdump_path": evidence["pcdump_path"],
            "source_hunks": evidence["source_hunks"],
            "target_score": evidence["target_score"],
            "expression_score": evidence["expression_score"],
            "stack_frame_facts": evidence["stack_frame_facts"],
            "target_virtual_facts": evidence["target_virtual_facts"],
            "expression_virtual_facts": evidence["expression_virtual_facts"],
        },
        "source_model_proof": {
            "next_unsupported_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "stack_clean_no_anchor_evidence": evidence,
        },
    }


def _draw_stack_clean_no_anchor_terminal():
    terminal = _draw_product_translate_terminal()
    evidence = _draw_stack_clean_no_anchor_evidence()
    proof = terminal["source_model_proof"]
    synthesis = proof["source_family_synthesis"]
    for target in (proof, synthesis):
        target["attempted_equivalence_classes"] = [
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ]
        target["next_unsupported_source_family"] = (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        )
        target["stack_clean_no_anchor_evidence"] = evidence
    synthesis["exhausted_dimensions"] = [
        {"dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}
    ]
    return terminal


def _sort_source_model_terminal_artifact(
    *,
    dimension: str,
    family: str,
    model: str,
    candidate_prefix: str,
):
    row = {
        "candidate_id": f"{candidate_prefix}nested-text-total-decision",
        "dimension_id": dimension,
        "family": "post_meta_ceiling_sort_source_family_synthesis",
        "strategy": dimension,
        "classification": "structural-blocked",
        "target_matched": 1,
        "target_targeted": 2,
        "target_virtual_distance": 1,
        "source_retained": "build/probes/sort-post-broader.c",
        "pcdump_path": "build/probes/sort-post-broader.pcdump.txt",
        "source_hunks": [{"hunk_id": "h001", "old_lines": ["old"], "new_lines": ["new"]}],
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 22,
        },
        "target_score": {
            "matched": 1,
            "targeted": 2,
            "virtual_distance": 1,
            "virtuals": {
                "34": {"expected": 27, "actual": 24, "matched": False},
                "44": {"expected": 25, "actual": 25, "matched": True},
            },
        },
    }
    exhausted = [
        {
            "dimension_id": dimension,
            "status": "scored-terminal",
            "candidate_ids": [row["candidate_id"]],
        }
    ]
    source_hunks_by_candidate = [
        {
            "candidate_id": row["candidate_id"],
            "dimension_id": dimension,
            "source_hunks": row["source_hunks"],
        }
    ]
    synthesis = {
        "status": "synthesis-exhausted",
        "attempted_equivalence_classes": [dimension],
        "exhausted_dimensions": exhausted,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "scored_candidate_ids": [row["candidate_id"]],
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "next_unsupported_source_model": model,
        "next_unsupported_source_family": family,
        "terminal_blockers": [
            {"reason": "protected-targets-not-jointly-preserved", "dimension_id": dimension}
        ],
    }
    proof = {
        "candidate_scores": [row],
        "retained_scored_probes": [row],
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
        "terminal_reason": f"{dimension}-exhausted/protected-targets-not-jointly-preserved",
        "family_id": "post_meta_ceiling_sort_source_family_synthesis",
        "next_unsupported_source_model": model,
        "next_unsupported_source_family": family,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "exhausted_dimensions": exhausted,
        "source_family_synthesis": synthesis,
        "source_model_proof": proof,
    }


def _sort_cross_tu_split_score_row(candidate_id, *, hit_virtual):
    ig34_matched = hit_virtual == "34"
    ig44_matched = hit_virtual == "44"
    return {
        "candidate_id": candidate_id,
        "dimension_id": SORT_CROSS_TU_DIMENSION,
        "family": "post_meta_ceiling_sort_source_family_synthesis",
        "strategy": SORT_CROSS_TU_DIMENSION,
        "classification": "structural-blocked",
        "target_matched": 1,
        "target_targeted": 2,
        "target_virtual_distance": 1,
        "source_retained": f"build/probes/{candidate_id}.c",
        "pcdump_path": f"build/probes/{candidate_id}.pcdump.txt",
        "source_hunks": [
            {"hunk_id": f"{candidate_id}-h001", "old_lines": ["old"], "new_lines": ["new"]}
        ],
        "structural_guard": {
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 5,
        },
        "target_score": {
            "matched": 1,
            "targeted": 2,
            "virtual_distance": 1,
            "virtuals": {
                "34": {
                    "expected": 27,
                    "actual": 27 if ig34_matched else 22,
                    "matched": ig34_matched,
                },
                "44": {
                    "expected": 25,
                    "actual": 25 if ig44_matched else 22,
                    "matched": ig44_matched,
                },
            },
        },
    }


def _sort_cross_tu_no_modeled_terminal_artifact():
    rows = [
        _sort_cross_tu_split_score_row("sort-cross-tu-ig34-only", hit_virtual="34"),
        _sort_cross_tu_split_score_row("sort-cross-tu-ig44-only", hit_virtual="44"),
    ]
    source_hunks_by_candidate = [
        {
            "candidate_id": row["candidate_id"],
            "dimension_id": SORT_CROSS_TU_DIMENSION,
            "source_hunks": row["source_hunks"],
        }
        for row in rows
    ]
    synthesis = {
        "status": "synthesis-exhausted",
        "attempted_equivalence_classes": [SORT_CROSS_TU_DIMENSION],
        "exhausted_dimensions": [
            {
                "dimension_id": SORT_CROSS_TU_DIMENSION,
                "status": "scored-terminal",
                "candidate_ids": [row["candidate_id"] for row in rows],
            }
        ],
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
        "next_unsupported_source_family": SORT_POST_CROSS_TU_FAMILY,
        "terminal_blockers": [SORT_CROSS_TU_NO_MODELED_BLOCKER],
        "one_hit_summary": {
            "one_hit_targets": ["34", "44"],
            "protected_targets_not_jointly_preserved": True,
        },
    }
    proof = {
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "source_family_synthesis": synthesis,
        "attempted_equivalence_classes": [SORT_CROSS_TU_DIMENSION],
        "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
        "next_unsupported_source_family": SORT_POST_CROSS_TU_FAMILY,
        "terminal_blockers": [SORT_CROSS_TU_NO_MODELED_BLOCKER],
    }
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": (
            "post-meta-gpr-one-hit-source-family-continuation-exhausted/"
            "protected-structural-ceiling"
        ),
        "family_id": "post_meta_ceiling_sort_source_family_synthesis",
        "next_unsupported_source_model": SORT_CROSS_TU_MODEL,
        "next_unsupported_source_family": SORT_POST_CROSS_TU_FAMILY,
        "candidate_scores": rows,
        "retained_scored_probes": rows,
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "exhausted_dimensions": synthesis["exhausted_dimensions"],
        "source_family_synthesis": synthesis,
        "source_model_proof": proof,
    }


def _sort_protected_loss_recombine_artifact(
    *,
    required_assignments: dict[str, int] | None = None,
):
    required = required_assignments or _sort_force()

    def combo(candidate_id, parents, *, ig34_actual, ig44_actual):
        row = _sort_cross_tu_split_score_row(
            candidate_id,
            hit_virtual="34",
        )
        row["dimension_id"] = "sort-protected-loss-init-lifetime"
        row["target_score"]["virtuals"]["34"]["actual"] = ig34_actual
        row["target_score"]["virtuals"]["34"]["matched"] = ig34_actual == 27
        row["target_score"]["virtuals"]["44"]["actual"] = ig44_actual
        row["target_score"]["virtuals"]["44"]["matched"] = ig44_actual == 25
        row["target_score"]["matched"] = int(ig34_actual == 27) + int(
            ig44_actual == 25
        )
        row["target_score"]["virtual_distance"] = 2 - row["target_score"]["matched"]
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


def _sort_post_cross_tu_broader_natural_terminal_artifact():
    return _sort_source_model_terminal_artifact(
        dimension=SORT_POST_CROSS_TU_BROADER_NATURAL_DIMENSION,
        family=SORT_POST_CROSS_TU_BROADER_NATURAL_FAMILY,
        model=SORT_POST_CROSS_TU_BROADER_NATURAL_MODEL,
        candidate_prefix="post-meta-sort-post-cross-tu-broader-natural-rewrite-",
    )


def _sort_post_broader_inline_boundary_terminal_artifact():
    return _sort_source_model_terminal_artifact(
        dimension=SORT_POST_BROADER_INLINE_BOUNDARY_DIMENSION,
        family=SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY,
        model=SORT_POST_BROADER_INLINE_BOUNDARY_MODEL,
        candidate_prefix="post-meta-sort-post-broader-natural-inline-boundary-",
    )


def _sort_post_inline_boundary_selection_emission_terminal_artifact():
    return _sort_source_model_terminal_artifact(
        dimension=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_DIMENSION,
        family=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY,
        model=SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_MODEL,
        candidate_prefix="post-meta-sort-post-inline-boundary-selection-emission-",
    )


def _sort_stale_selection_swap_terminal_with_post_inline_attempt():
    stale = _sort_source_model_terminal_artifact(
        dimension=SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_DIMENSION,
        family=SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY,
        model=SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_MODEL,
        candidate_prefix="post-meta-sort-post-cross-tu-source-hypothesis-",
    )
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


def _draw_post_stack_clean_no_anchor_source_shape_terminal():
    terminal = _draw_stack_clean_no_anchor_terminal()
    retained = [
        {
            "candidate_id": (
                "draw-post-stack-clean-no-anchor-shape-digit-base-post-anim-temp"
            ),
            "target_score": {
                "matched": 0,
                "targeted": 3,
                "virtuals": {
                    "32": {"expected": 28, "actual": 26},
                    "37": {"expected": 26, "actual": None},
                    "46": {"expected": 26, "actual": 2},
                },
            },
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 22,
                "rejection_reason": "signature-type-mismatch",
            },
            "pcdump_path": "build/post-stack-digit-base.pcdump.txt",
        },
        {
            "candidate_id": (
                "draw-post-stack-clean-no-anchor-shape-row-delta-callsite-"
                "late-materialize"
            ),
            "target_score": {"matched": 0, "targeted": 3},
            "structural_guard": {
                "accepted": False,
                "normalized_diff_lines": 0,
                "expected_frame": 168,
                "current_frame": 184,
                "frame_delta": 16,
            },
            "pcdump_path": "build/post-stack-row-delta.pcdump.txt",
        },
    ]
    evidence = {
        "ranked_post_stack_clean_probes": retained,
        "best_candidate_id": retained[0]["candidate_id"],
    }
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
        target["next_unsupported_source_family"] = (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
        )
        target["post_stack_clean_no_anchor_evidence"] = evidence
        target["retained_scored_probes"] = retained
    terminal["terminal_reason"] = (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )
    terminal["post_stack_clean_no_anchor_evidence"] = evidence
    return terminal


def _draw_post_stack_loop_callsite_source_context_terminal():
    terminal = _draw_post_stack_clean_no_anchor_source_shape_terminal()
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
            },
            "pcdump_path": "build/post-stack-loop-callsite.pcdump.txt",
        }
    ]
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
        target["next_unsupported_source_family"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
        )
        target["next_unsupported_source_model"] = (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
        )
        target["next_unsupported_source_dimension"] = None
        target["retained_scored_probes"] = retained
    terminal["terminal_reason"] = (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    return terminal


def _draw_stack_clean_no_anchor_retained_frontiers_aggregate(*, actionable=False):
    lane = _draw_stack_clean_no_anchor_lane() if actionable else None
    terminal = _draw_stack_clean_no_anchor_terminal() if not actionable else None
    return {
        "status": "actionable" if actionable else "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": [lane] if lane is not None else [],
                "terminal_frontiers": [terminal] if terminal is not None else [],
                "next_frontier": lane,
                "summary": {
                    "unexhausted_count": 1 if lane is not None else 0,
                    "terminal_count": 1 if terminal is not None else 0,
                },
            }
        ],
        "next_frontier": lane,
    }


def _draw_stack_clean_final_with_stale_helper_aggregate():
    stack = _draw_stack_clean_no_anchor_retained_frontiers_aggregate()
    helper = _draw_helper_boundary_terminal_retained_frontiers_aggregate()
    stack_entry = stack["functions"][0]
    helper_entry = helper["functions"][0]
    stack_entry["terminal_frontiers"].extend(helper_entry["terminal_frontiers"])
    stack_entry["summary"]["terminal_count"] = len(stack_entry["terminal_frontiers"])
    return stack


def _draw_post_stack_clean_with_stale_stack_aggregate():
    aggregate = _draw_stack_clean_no_anchor_retained_frontiers_aggregate()
    entry = aggregate["functions"][0]
    entry["terminal_frontiers"].append(
        _draw_post_stack_clean_no_anchor_source_shape_terminal()
    )
    entry["summary"]["terminal_count"] = len(entry["terminal_frontiers"])
    return aggregate


def _draw_helper_boundary_lane():
    return {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-helper-boundary-candidate",
        "family_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "suppression_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff",
        "status": "source-actionable",
        "terminal": False,
        "actionable": True,
        "dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "source_model_layer_dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "continuation": {
            "route": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
            "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
            "source_retained": "build/draw/helper-boundary-seed.c",
            "pcdump_path": "build/draw/helper-boundary-seed.pcdump.txt",
            "source_hunks": [{"hunk_id": "helper-boundary-seed"}],
            "target_score": {"matched": 0, "targeted": 3},
            "expression_score": {"matched": 0, "targeted": 3},
        },
        "source_model_proof": {
            "next_unsupported_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
            "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        },
    }


def _draw_helper_boundary_retained_frontiers_aggregate():
    lane = _draw_helper_boundary_lane()
    return {
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
        "next_frontier": lane,
    }


def _draw_helper_boundary_terminal_retained_frontiers_aggregate():
    terminal_blockers = [
        {
            "reason": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
            "count": 2,
            "candidate_ids": ["void-helper-0001", "void-helper-0002"],
        },
        {
            "reason": DRAW_HELPER_BOUNDARY_REJECTION_REASON,
            "count": 2,
            "candidate_ids": ["void-helper-0001", "void-helper-0002"],
        },
    ]
    terminal = {
        "function": "mnDiagram_DrawCellNumber",
        "frontier_id": "draw-helper-boundary-terminal",
        "family_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "suppression_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blocker": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        "next_unsupported_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
        "terminal_blockers": terminal_blockers,
        "source_model_proof": {
            "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal",
            "status": "terminal",
            "terminal_blocker": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
            "terminal_blockers": terminal_blockers,
            "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
            "next_unsupported_source_dimension": (
                DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
            ),
            "next_unsupported_source_family": (
                DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
            ),
            "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
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
                "terminal_blocker": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
                "terminal_blockers": terminal_blockers,
            },
        },
    }
    return {
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
        "next_frontier": None,
    }


def _directed_exhausted(function="fn_test"):
    blocked = [
        {
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
        }
    ]
    return {
        "function": function,
        "unit": "melee/mn/mndiagram",
        "gate": {
            "passed": False,
            "reason": "no_smooth_gradient",
            "evidence": {
                "n_treatment": 3,
                "best_delta": 0.0,
            },
        },
        "directed_telemetry": [
            {
                "valid": True,
                "applied_mutator": "transform-corpus:coloring_register_steering:0",
                "checkdiff_gate": "byte_mismatch",
                "proof_assignments": {
                    "satisfied": [],
                    "blocked": blocked,
                    "abstained": [],
                },
                "non_actionable": False,
            },
            {
                "valid": True,
                "applied_mutator": "reorder_local_decls",
                "checkdiff_gate": "byte_mismatch",
                "proof_assignments": {
                    "satisfied": [],
                    "blocked": blocked,
                    "abstained": [],
                },
                "non_actionable": True,
            },
        ],
        "accounting": {
            "compiled": 2,
            "budget_exhausted": False,
            "source_shape_drained": True,
            "producer_failed": 0,
        },
    }


def _expression_interferer_terminal(function="fn_test", *, include_scope=True):
    payload = {
        "status": "blocked",
        "kind": "expression-scored-fpr-case-a-c2-exhaustion",
        "attempted_families": [
            "row-fsubs-owner-repair",
            "non-satisfied-select-order",
            "expression-aware-source-generation",
            "sticky-pool-bridge",
        ],
        "post_bridge_terminal_summary": {
            "status": "blocked",
            "kind": "no-expression-progress-after-row-fsubs-and-support-orders",
            "terminal_blocker": "current-source-shape-allocator-ceiling",
            "exhausted_routes": [
                "row_fsubs_owner_repair",
                "non_satisfied_select_order",
            ],
            "evidence": {
                "candidate_count": 9,
                "best_expression_matched": 0,
                "best_expression_targeted": 2,
                "best_expression_virtual_distance": 2,
                "focus": "col_offset",
                "focus_ig": 32,
                "paired_source": "row_offset",
                "paired_ig": 37,
                "current_focus_reg": 26,
                "current_paired_reg": 28,
                "target_reg": 28,
                "paired_target_reg": 26,
            },
        },
        "source_generation": {
            "status": "blocked",
            "kind": "expression-aware-source-generation",
            "terminal_blocker": "current-source-shape-allocator-ceiling",
            "suppressed_families": [
                "row_fsubs_owner_repair",
                "product_operand_ownership",
            ],
        },
    }
    if include_scope:
        payload["source_generation"]["function"] = function
    return payload


def _select_order_residual_case_c(function="fn_test"):
    source = {
        "kind": "copy/coalesce-product",
        "expression": "mr r34,r37",
        "source_file": "candidate.c",
        "source_line": None,
        "base_virtual": 37,
        "confidence": "pcode-first-def",
        "first_def": {
            "pass_name": "BEFORE GLOBAL OPTIMIZATION",
            "block_idx": 13,
            "instr_idx": 0,
            "opcode": "mr",
            "operands": "r34,r37",
        },
    }
    return {
        "function": function,
        "status": "ok",
        "source_bridge_summary": {
            "status": "blocked",
            "dominant_blocker": "source-probes-exhausted",
            "leads": [
                {
                    "target_ig": 34,
                    "checkdiff_target_reg": 27,
                    "order_move": ["after", 32],
                    "source": source,
                    "source_attributed": True,
                    "source_actionable": False,
                    "terminal_blocker": "implicit-temp-no-safe-source-move",
                    "source_probe_diagnostic": {
                        "status": "blocked",
                        "target_ig": 34,
                        "terminal_blocker": "implicit-temp-no-safe-source-move",
                        "source_attribution": source,
                    },
                },
                {
                    "target_ig": 44,
                    "checkdiff_target_reg": 25,
                    "source": {
                        "kind": "implicit-temp",
                        "expression": "add r44,r52,r64",
                    },
                    "source_attributed": True,
                    "source_actionable": True,
                    "source_probe_diagnostic": {
                        "status": "materialized",
                        "materialized_probe_labels": [
                            "window-order-ranked-indexed-byte-ig44-before-0"
                        ],
                    },
                },
            ],
        },
        "terminal_exhaustion_summary": {
            "status": "blocked",
            "terminal_blocker": "transform-family-exhausted",
            "dominant_blocker": "source-probes-exhausted",
            "blocker_targets": [34],
            "best_retained_variants": [
                {
                    "label": "type-width-0",
                    "source_retained": "build/probes/type-width-0.c",
                }
            ],
        },
    }


def _sort_live_implicit_temp_node_delta(function="mnDiagram_SortNamesByKOs"):
    return {
        "function": function,
        "class_id": 0,
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": function,
            "blocker": "structurally-different-virtual",
            "missing_virtuals": [
                {
                    "target_ig": 34,
                    "desired_registers": ["r27"],
                    "current_register": "r24",
                    "source": {
                        "kind": "implicit-temp",
                        "name": None,
                        "type": None,
                        "source_file": None,
                        "source_line": None,
                        "source_col": None,
                        "expression": "addi r34,r39,1",
                        "confidence": "pcode-first-def",
                    },
                },
                {
                    "target_ig": 44,
                    "desired_registers": ["r25"],
                    "current_register": "r27",
                    "source": {
                        "kind": "implicit-temp",
                        "name": None,
                        "type": None,
                        "source_file": None,
                        "source_line": None,
                        "source_col": None,
                        "expression": "add r44,r49,r34",
                        "confidence": "pcode-first-def",
                    },
                },
            ],
        },
    }


def _sort_live_select_order_materialized_implicit_temps(
    function="mnDiagram_SortNamesByKOs",
):
    def lead(target_ig, expression, label):
        return {
            "target_ig": target_ig,
            "source": {
                "kind": "implicit-temp",
                "name": None,
                "type": None,
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": None,
                "source_col": None,
                "expression": expression,
                "confidence": "pcode-first-def",
            },
            "source_attributed": True,
            "source_actionable": True,
            "source_probe_diagnostic": {
                "status": "materialized",
                "target_ig": target_ig,
                "materialized_probe_labels": [label],
            },
        }

    return {
        "function": function,
        "status": "ok",
        "source_bridge_summary": {
            "status": "blocked",
            "dominant_blocker": "source-probes-exhausted",
            "leads": [
                lead(34, "addi r34,r39,1", "implicit-temp-ig34@0"),
                lead(44, "add r44,r49,r34", "implicit-temp-ig44@0"),
            ],
        },
        "terminal_exhaustion_summary": {
            "status": "blocked",
            "terminal_blocker": "transform-family-exhausted",
            "dominant_blocker": "source-probes-exhausted",
            "blocker_targets": [34, 44],
            "best_retained_variants": [
                {"source_retained": "build/probes/sort-implicit-temp@0.c"}
            ],
        },
    }


def _sort_node_set_split_zero_bindable(function="mnDiagram_SortNamesByKOs"):
    return {
        "function": function,
        "status": "blocked",
        "generated_count": 0,
        "scored_count": 0,
        "evaluated_count": 0,
        "pending_count": 0,
        "realized_count": 0,
        "objective_counts": {},
        "wrong_register_exhausted": False,
        "stop_reason": "no-coupled-probes",
        "blocked_reason": (
            "coupled mode needs >=2 bindable missing virtuals (found 0)"
        ),
        "coupled_requests": [],
        "in_place_recolor": {
            "status": "insufficient-source-bindings",
            "target_igs": [],
        },
    }


def _sort_copy_survived_terminal(function="mnDiagram_SortNamesByKOs"):
    return {
        "function": function,
        "copy_survived_repair": {
            "status": "terminal-blocker",
            "trace_status": "copy-found",
            "likely_cause": "copy-survived-distinct-phys",
            "transform_category": "copy-survived",
            "register_class": "gpr",
            "class_id": 0,
            "from_virtual": 34,
            "to_virtual": 41,
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


def _residual_simplify_exhausted(function="fn_test"):
    return {
        "function": function,
        "terminal_blocker": "no-retained-candidate-improved-residual-force-phys",
        "source_file": "/tmp/work/build/probes/type-width-0.c",
        "retained_mode": True,
        "residual_force_phys": {"34": 27, "44": 25},
        "summary": {
            "compiled": 72,
            "skipped": 9,
            "progress_hits": 0,
        },
        "ranked_probes": [
            {
                "rank": 1,
                "provenance": "decl-orders demote dst",
                "force_phys_distance_total": 3,
            },
            {
                "rank": 2,
                "provenance": "decl-orders demote j",
                "force_phys_distance_total": 3,
            },
        ],
    }


def _target_only_simplify_exhausted(
    function="fn_test",
    *,
    force_phys=None,
):
    if force_phys is None:
        force_phys = {"40": 25}
    return {
        "function": function,
        "terminal_blocker": "no-retained-candidate-improved-residual-force-phys",
        "source_file": "/tmp/work/build/probes/target-only@0.c",
        "retained_mode": True,
        "residual_force_phys": dict(force_phys),
        "force_phys": dict(force_phys),
        "summary": {
            "compiled": 77,
            "skipped": 10,
            "compile_failures": 32,
            "gate_rejected": 45,
            "progress_hits": 0,
        },
        "ranked_probes": [],
        "resume": {
            "skipped_count": 10,
            "candidate_stream_position": 87,
            "next_skip_first_candidates": 87,
        },
    }


def _target_only_addi_copy_product_resolver(function="fn_test"):
    return {
        "function": function,
        "kind": "target-only-backprojection-addi-copy-product-source-resolver",
        "status": "terminal-non-source-visible",
        "complete": True,
        "source_lever": "addi r34,r52,28",
        "pcode_lever": {
            "dst_virtual": 34,
            "base_virtual": 52,
            "immediate": 28,
        },
        "copy_product_chain": [
            {
                "target_ig": 34,
                "expression": "mr r34,r37",
                "kind": "copy/coalesce-product",
            },
            {
                "target_ig": 37,
                "expression": "addi r37,r52,28",
                "kind": "pcode-only-address-owner",
            },
            {
                "target_ig": 44,
                "expression": "add r44,r52,r64",
                "kind": "protected-copy-product",
                "protected": True,
            },
        ],
        "source_visible_variants": [
            {
                "label": "source-visible-address-owner@0",
                "score": 266,
                "target_score": {"matched": 0, "targeted": 2},
                "target_hits": 0,
                "protected_preserved": False,
            },
            {
                "label": "source-visible-address-owner@1",
                "score": 626,
                "target_score": {"matched": 0, "targeted": 2},
                "target_hits": 0,
                "protected_preserved": True,
            },
        ],
        "attempted_targets": {"34": 25},
        "protected_targets": {"44": 25},
        "final_force_phys": {"34": 25, "44": 25},
        "source_file": "/tmp/work/build/probes/target-only@0.c",
        "pcdump": "/tmp/work/build/probes/target-only@0.pcdump.txt",
        "baseline_score": 900,
        "best_score": 626,
        "terminal_blocker": "addi-copy-product-operands-not-source-visible",
    }


def _plan_transform_simplify_summary(
    function="fn_test",
    *,
    kind="retained-source-case-c-simplify-order-continuation",
    terminal_blocker="bounded-remote-scored-exhaustion-no-simplify-order-movement",
    source_retained="/tmp/work/build/probes/type-width-0.c",
):
    return {
        "function": function,
        "retained_case_c_simplify_order_continuation_summary": {
            "status": "exhausted",
            "kind": kind,
            "terminal_blocker": terminal_blocker,
            "evaluated_probe_count": 6,
            "exact_count": 0,
            "residual_hit_count": 0,
            "lost_lower_drift_count": 2,
            "first_divergence_moved_count": 0,
            "best_retained_candidates": [
                {
                    "probe_id": "retained_gpr_case_c_simplify_order_continuation@0",
                    "source_retained": source_retained,
                    "pcdump_path": source_retained.replace(".c", ".pcdump.txt"),
                }
            ],
        },
    }


def _post_source_owner_backtrack_exhausted(function="fn_test"):
    return {
        "function": function,
        "plan": {"function": function},
        "retained_case_c_post_source_owner_backtrack_summary": {
            "status": "scored-negative",
            "kind": "retained-source-case-c-post-source-owner-backtrack",
            "terminal_blocker": "post-source-owner-exhausted",
            "protected_targets": {"44": 25},
            "attempted_targets": {"34": 27},
            "evaluated_probe_count": 2,
            "lost_protected_count": 2,
            "unscoreable_count": 0,
            "exact_count": 0,
            "best_retained_candidates": [
                {
                    "probe_id": (
                        "retained_gpr_case_c_post_source_owner_backtrack@0"
                    ),
                    "source_retained": "build/probes/post-owner@0.c",
                    "window_order_label": (
                        "window-order-ranked-indexed-byte-ig34-after-1"
                    ),
                    "source_attribution_kind": "copy/coalesce-product",
                    "post_source_owner_backtrack": {
                        "skipped_current_owner_labels": [
                            "window-order-ranked-indexed-byte-ig34-after-0"
                        ],
                        "candidate_rank": 3,
                        "span_text": (
                            "sorted_names_totals_idx_probe_2 = "
                            "mnDiagram_804A076C.sorted_names[j];"
                        ),
                    },
                    "target_score": {
                        "matched": 0,
                        "targeted": 2,
                        "virtuals": {
                            "34": {
                                "expected": 27,
                                "actual": 29,
                                "matched": False,
                            },
                            "44": {
                                "expected": 25,
                                "actual": 27,
                                "matched": False,
                            },
                        },
                    },
                }
            ],
        },
    }


def _common_subexpr_coalesce_exhausted(function="fn_test"):
    return {
        "function": function,
        "plan": {"function": function},
        "validation_summary": {
            "retained_gpr_common_subexpr_coalesce_source_summary": {
                "status": "scored-negative",
                "kind": "retained-gpr-common-subexpr-coalesce-source",
                "terminal_blocker": (
                    "common-subexpr-coalesce-source-probes-exhausted"
                ),
                "protected_targets": {"44": 25},
                "attempted_targets": {"34": 27, "40": 25},
                "materialized_probe_count": 2,
                "evaluated_probe_count": 2,
                "exact_count": 0,
                "best_retained_candidates": [
                    {
                        "probe_id": (
                            "retained_gpr_common_subexpr_coalesce_source@0"
                        ),
                        "source_retained": "build/probes/common-subexpr@0.c",
                        "coalesce_pair": {"from": 34, "to": 40},
                        "common_source_virtual": 37,
                        "source_owner_strategy": (
                            "common-source-shared-base-temp"
                        ),
                        "source_hunks": [
                            {
                                "kind": (
                                    "common-subexpr-source-owner-shared-base"
                                ),
                                "line_start": 12,
                                "replacement_text": (
                                    "u8* common_source_r37_probe = dst;"
                                ),
                            }
                        ],
                        "target_score": {
                            "matched": 0,
                            "targeted": 2,
                            "virtuals": {
                                "34": {
                                    "expected": 27,
                                    "actual": 29,
                                    "matched": False,
                                },
                                "40": {
                                    "expected": 25,
                                    "actual": 27,
                                    "matched": False,
                                },
                            },
                        },
                    }
                ],
            },
        },
    }


def _common_subexpr_coalesce_residual_hit(function="fn_test"):
    source_retained = "/tmp/work/build/probes/common-subexpr@0.c"
    return {
        "plan": {"function": function},
        "validation_summary": {
            "retained_gpr_common_subexpr_coalesce_source_summary": {
                "status": "residual-hit",
                "kind": "retained-gpr-common-subexpr-coalesce-source",
                "stop_condition": "common-subexpr-coalesce-source-residual-hit",
                "protected_targets": {"34": 27, "44": 25},
                "attempted_targets": {},
                "materialized_probe_count": 2,
                "evaluated_probe_count": 2,
                "exact_count": 0,
                "preserved_force_phys": {"44": 25},
                "residual_force_phys": {"34": 27, "44": 25},
                "best_retained_candidates": [
                    {
                        "probe_id": (
                            "retained_gpr_common_subexpr_coalesce_source@0"
                        ),
                        "source_retained": source_retained,
                        "pcdump_path": source_retained.replace(
                            ".c", ".pcdump.txt"
                        ),
                        "coalesce_pair": {"from": 35, "to": 42},
                        "common_source_virtual": 39,
                        "source_owner_strategy": (
                            "common-source-shared-base-temp"
                        ),
                        "source_owner_candidates": [
                            {
                                "var": "dst_iter",
                                "line": 926,
                                "type": "u8*",
                                "rhs": "dst",
                                "kind": "assignment",
                            }
                        ],
                        "source_hunks": [
                            {
                                "kind": (
                                    "common-subexpr-source-owner-shared-base"
                                ),
                                "line_start": 12,
                                "replacement_text": (
                                    "u8* common_source_r39_probe = dst;"
                                ),
                            }
                        ],
                        "target_score": {
                            "matched": 1,
                            "targeted": 2,
                            "virtuals": {
                                "34": {
                                    "expected": 27,
                                    "actual": 29,
                                    "matched": False,
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
            },
        },
    }


def _first_divergence_advisory():
    return {
        "kind": "allocator-first-divergence",
        "fact": {
            "class_id": 0,
            "ig_idx": 34,
            "case": "C2",
            "baseline_reg": 29,
            "target_reg": 27,
        },
        "source": {
            "ig_idx": 34,
            "var_name": "dst_iter",
            "confidence": "low-confidence",
            "candidate_spans": [],
        },
    }


def _target_live_range_blocker_chain_exhausted(
    function="fn_test",
    *,
    status="blocked",
    evaluated=2,
    unscoreable=0,
):
    return {
        "function": function,
        "plan": {"function": function},
        "validation_summary": {
            "retained_case_c_target_live_range_repair_summary": {
                "status": status,
                "kind": "retained-source-case-c-target-live-range-interference",
                "terminal_blocker": (
                    "blocker-color-chain-source-probes-exhausted"
                ),
                "dominant_blocker": "blocker-color-chain-source-probes",
                "protected_targets": {"34": 27},
                "attempted_targets": {"44": 25},
                "evaluated_probe_count": evaluated,
                "unscoreable_count": unscoreable,
                "exact_count": 0,
                "blocker_color_chains": [[
                    {
                        "target_ig": 34,
                        "target_phys": 27,
                        "blocker_ig": 44,
                        "blocker_phys": 27,
                        "blocker_source": {
                            "kind": "implicit-temp",
                            "expression": "add r44,r52,r64",
                            "source_file": "build/probes/blocker-chain@0.c",
                            "source_line": None,
                            "confidence": "pcode-first-def",
                            "first_def": {
                                "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                                "opcode": "add",
                                "operands": "r44,r52,r64",
                            },
                        },
                        "blocker_operand_sources": [
                            {
                                "operand_index": 1,
                                "operand_virtual": 52,
                                "operand_assigned_reg": 24,
                                "source": {
                                    "kind": "local",
                                    "expression": "case_c_max_idx_probe",
                                    "source_file": (
                                        "build/probes/blocker-chain@0.c"
                                    ),
                                    "source_line": 12,
                                    "confidence": "source-owner",
                                },
                            },
                            {
                                "operand_index": 2,
                                "operand_virtual": 64,
                                "operand_assigned_reg": 28,
                                "source": {
                                    "kind": "local",
                                    "expression": (
                                        "sorted_names_totals_idx_probe_2"
                                    ),
                                    "source_file": (
                                        "build/probes/blocker-chain@0.c"
                                    ),
                                    "source_line": 14,
                                    "confidence": "source-owner",
                                },
                            },
                        ],
                    },
                    {
                        "target_ig": 44,
                        "target_phys": 25,
                        "blocker_ig": 41,
                        "blocker_phys": 25,
                        "blocker_source": {
                            "kind": "implicit-temp",
                            "expression": "rlwinm r41,r45,0,24,31",
                            "source_file": "build/probes/blocker-chain@0.c",
                            "source_line": None,
                            "confidence": "pcode-first-def",
                            "first_def": {
                                "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                                "opcode": "rlwinm",
                                "operands": "r41,r45,0,24,31",
                            },
                        },
                        "blocker_operand_sources": [
                            {
                                "operand_index": 1,
                                "operand_virtual": 45,
                                "operand_assigned_reg": 26,
                                "source": {
                                    "kind": "local",
                                    "expression": (
                                        "window_order_mnDiagram_804A076C_"
                                        "sorted_names_index_probe"
                                    ),
                                    "source_file": (
                                        "build/probes/blocker-chain@0.c"
                                    ),
                                    "source_line": 16,
                                    "confidence": "source-owner",
                                },
                            },
                        ],
                    },
                ]],
                "exhausted_strategy_spans": [
                    {
                        "probe_id": (
                            "retained_gpr_case_c_target_live_range_repair@0"
                        ),
                        "source_probe_provenance_kind": (
                            "target-aware-value-side-temp"
                        ),
                        "ranked_repair_candidate": {
                            "strategy": "value-side-duplicate-temp",
                            "source_expression": "sorted_names[j]",
                            "address_expression": (
                                "mnDiagram_804A076C.sorted_names[max_idx]"
                            ),
                        },
                        "exhaustion_key": "value-side-duplicate-temp:sorted_names[j]",
                    },
                ],
                "best_retained_candidates": [
                    {
                        "probe_id": (
                            "retained_gpr_case_c_target_live_range_repair@0"
                        ),
                        "source_retained": "build/probes/blocker-chain@0.c",
                        "ranked_repair_candidate": {
                            "strategy": "value-side-duplicate-temp",
                            "source_expression": "sorted_names[j]",
                        },
                        "blocker_color_chain": [
                            {
                                "target_ig": 34,
                                "target_phys": 27,
                                "blocker_ig": 44,
                                "blocker_phys": 27,
                            },
                            {
                                "target_ig": 44,
                                "target_phys": 25,
                                "blocker_ig": 41,
                                "blocker_phys": 25,
                            },
                        ],
                        "target_score": {
                            "matched": 1,
                            "targeted": 2,
                            "virtuals": {
                                "34": {
                                    "expected": 27,
                                    "actual": 27,
                                    "matched": True,
                                },
                                "44": {
                                    "expected": 25,
                                    "actual": 27,
                                    "matched": False,
                                },
                            },
                        },
                    }
                ],
            },
        },
    }


def _target_live_range_fpr_interference_exhausted(function="fn_test"):
    return {
        "function": function,
        "plan": {"function": function},
        "validation_summary": {
            "retained_case_c_target_live_range_repair_summary": {
                "status": "blocked",
                "kind": "retained-source-case-c-target-live-range-interference",
                "terminal_blocker": (
                    "target-aware-live-range-interference-probes-exhausted"
                ),
                "protected_targets": {"32": 26},
                "attempted_targets": {"37": 26},
                "evaluated_probe_count": 3,
                "unscoreable_count": 0,
                "exact_count": 0,
                "blocker_color_chains": [],
                "exhausted_strategy_spans": [
                    {
                        "probe_id": (
                            "retained_fpr_case_c_target_live_range_repair@0"
                        ),
                        "source_probe_provenance_kind": (
                            "target-aware-live-range-anchor"
                        ),
                        "ranked_repair_candidate": {
                            "strategy": "interferer-expression-temp",
                            "source_expression": "row_offset_adj",
                        },
                        "exhaustion_key": "target-aware-live-range-anchor",
                    },
                    {
                        "probe_id": (
                            "retained_fpr_case_c_target_live_range_repair@1"
                        ),
                        "source_probe_provenance_kind": (
                            "target-aware-scalar-interference-shape"
                        ),
                        "ranked_repair_candidate": {
                            "strategy": "scalar-duplicate-temp",
                            "source_expression": "row_offset_adj",
                            "rewritten_expression": (
                                "target_repair_scalar_duplicate_ig37_probe"
                            ),
                        },
                        "exhaustion_key": (
                            "target-aware-scalar-interference-shape"
                        ),
                    },
                    {
                        "probe_id": (
                            "retained_fpr_case_c_target_live_range_repair@2"
                        ),
                        "source_probe_provenance_kind": (
                            "target-aware-scalar-pair-overlap"
                        ),
                        "ranked_repair_candidate": {
                            "strategy": "scalar-paired-overlap-temp",
                            "source_expression": "row_offset_adj",
                            "paired_source_expression": "col_offset",
                            "rewritten_expression": (
                                "target_repair_scalar_pair_ig37_probe"
                            ),
                        },
                        "exhaustion_key": "target-aware-scalar-pair-overlap",
                    },
                ],
                "best_retained_candidates": [
                    {
                        "probe_id": (
                            "retained_fpr_case_c_target_live_range_repair@0"
                        ),
                        "source_retained": "build/probes/draw-fpr@0.c",
                        "ranked_repair_candidate": {
                            "strategy": "interferer-expression-temp",
                            "source_expression": "row_offset_adj",
                        },
                    },
                    {
                        "probe_id": (
                            "retained_fpr_case_c_target_live_range_repair@1"
                        ),
                        "source_retained": "build/probes/draw-fpr@1.c",
                        "ranked_repair_candidate": {
                            "strategy": "scalar-duplicate-temp",
                            "source_expression": "row_offset_adj",
                        },
                    },
                    {
                        "probe_id": (
                            "retained_fpr_case_c_target_live_range_repair@2"
                        ),
                        "source_retained": "build/probes/draw-fpr@2.c",
                        "ranked_repair_candidate": {
                            "strategy": "scalar-paired-overlap-temp",
                            "source_expression": "row_offset_adj",
                        },
                    },
                ],
            },
        },
    }


def _target_live_range_fpr_anchor_only_exhausted(function="fn_test"):
    evidence = _target_live_range_fpr_interference_exhausted(function=function)
    summary = evidence["validation_summary"][
        "retained_case_c_target_live_range_repair_summary"
    ]
    summary["evaluated_probe_count"] = 3
    summary["exhausted_strategy_spans"] = summary["exhausted_strategy_spans"][:1]
    summary["best_retained_candidates"] = summary["best_retained_candidates"][:1]
    return evidence


def test_practical_ceiling_requires_all_negative_proofs():
    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "target-only-allocator-rotation"
    assert result["source_shape_exhausted"] is True
    assert result["wrong_register_exhausted"] is True
    assert result["node_set_delta"]["blocker"] == "structurally-different-virtual"
    assert result["force_vector"]["union_status"] == "match"
    assert result["exit_code"] == 3


def test_draw_aggregate_missing_force_vector_reports_concrete_command():
    result = classify_allocator_ceiling(
        [
            _draw_delta(),
            _draw_node_wrong(32),
            _draw_node_wrong(37),
            _draw_coupled_node_summary(),
            _draw_select_order_terminal(),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "incomplete"
    assert "force-phys verification with union status match" in (
        result["missing_evidence"]
    )
    assert "transform-corpus exhausted negative validation evidence" not in (
        result["missing_evidence"]
    )
    assert any(
        "debug solve coloring" in step and "--force-vector-probes" in step
        for step in result["next_steps"]
    )


def test_draw_aggregate_missing_coupled_node_set_reports_concrete_command():
    result = classify_allocator_ceiling(
        [
            _draw_delta(),
            _draw_node_wrong(32),
            _draw_node_wrong(37),
            _draw_select_order_terminal(),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "incomplete"
    assert any("coupled node-set-split" in item for item in result["missing_evidence"])
    assert any(
        "debug solve node-set-split" in step and "--coupled" in step
        for step in result["next_steps"]
    )


def test_draw_aggregate_coupled_budget_stop_is_bounded_with_resume():
    result = classify_allocator_ceiling(
        [
            _draw_delta(),
            _draw_node_wrong(32),
            _draw_node_wrong(37),
            _draw_coupled_node_summary(stop_kind="budget-exhausted"),
            _draw_select_order_terminal(),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "bounded"
    assert any("budget-exhausted" in reason for reason in result["bounded_reasons"])
    assert any("--resume-summary draw.json" in step for step in result["next_steps"])


def test_draw_force_vector_and_retained_pcdumps_enable_target_only_backprojection(
    tmp_path,
):
    result = classify_allocator_ceiling(
        [
            _draw_delta(),
            _draw_node_wrong(32),
            _draw_node_wrong(37),
            _draw_coupled_node_summary(),
            _draw_select_order_terminal(),
            _draw_force_vector_payload(tmp_path),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["select_order_fpr_case_c_exhaustion"]["complete"] is True
    assert "transform-corpus exhausted negative validation evidence" not in (
        result["missing_evidence"]
    )
    backprojection = result["target_only_allocator_backprojection"]
    assert backprojection["status"] == "source-actionable"
    assert backprojection["source_levers"]


def test_draw_force_vector_no_match_after_coupled_exhaustion_is_practical_ceiling(
    tmp_path,
):
    result = classify_allocator_ceiling(
        [
            _draw_delta(),
            _draw_node_wrong(32),
            _draw_node_wrong(37),
            _draw_coupled_node_summary(),
            _draw_select_order_terminal(),
            _draw_force_vector_payload(tmp_path, union_status="no_match"),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    assert (
        result["terminal_reason"]
        == "force-vector-no-match-after-draw-frontier-exhaustion"
    )
    assert result["missing_evidence"] == []
    assert result["source_shape_exhausted"] is True
    assert not any("--force-vector-probes" in step for step in result["next_steps"])
    assert result["force_vector"]["ran"] is True
    assert result["force_vector"]["union_status"] == "no_match"
    assert result["node_set_frontier_coverage"]["complete"] is True


def test_draw_force_vector_no_match_without_run_remains_incomplete(tmp_path):
    result = classify_allocator_ceiling(
        [
            _draw_delta(),
            _draw_node_wrong(32),
            _draw_node_wrong(37),
            _draw_coupled_node_summary(),
            _draw_select_order_terminal(),
            _draw_force_vector_payload(
                tmp_path,
                union_status="no_match",
                ran=False,
            ),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["ran"] is False
    assert result["force_vector"]["union_status"] == "no_match"
    assert "force-phys verification with union status match" in (
        result["missing_evidence"]
    )
    assert any("--force-vector-probes" in step for step in result["next_steps"])


def test_target_only_allocator_ceiling_backprojects_source_levers(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["source"] = {
        "kind": "local",
        "name": "target_value",
        "expression": "target_value",
        "confidence": "unit-test",
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert (
        result["terminal_reason"]
        == "target-only-allocator-rotation-backprojection"
    )
    backprojection = result["target_only_allocator_backprojection"]
    assert backprojection["status"] == "source-actionable"
    divergence = backprojection["divergences"][0]
    assert divergence["case"] in {"C", "C2", "A"}
    assert divergence["target_ig"] == 40
    assert divergence["natural_decision"]["assigned_phys"] == 29
    assert divergence["forced_decision"]["assigned_phys"] == 25
    assert backprojection["source_levers"]
    assert backprojection["source_levers"][0]["target_ig"] == 40
    assert backprojection["source_levers"][0]["source"]["expression"] == (
        "target_value"
    )


def test_target_only_addi_source_probe_exhaustion_waits_for_resolver_evidence(
    tmp_path,
):
    force = _force_match()
    force["force_vector"] = "class0:ig34:phys=r25,class0:ig44:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["target_ig"] = 34
    delta["missing_virtuals"][0]["source"] = {
        "kind": "implicit-temp",
        "expression": "addi r34,r52,28",
        "confidence": "pcode-first-def",
        "source_file": None,
        "source_line": None,
        "source_col": None,
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(
                tmp_path,
                target_ig=34,
                blocker_ig=44,
            ),
            _target_only_simplify_exhausted(force_phys={"34": 25, "44": 25}),
        ],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert (
        result["terminal_reason"]
        == "target-only-allocator-rotation-backprojection"
    )
    continuation = result[
        "target_only_backprojection_source_probe_continuation"
    ]
    assert continuation["status"] == "incomplete"
    assert continuation["complete"] is False
    assert continuation["source_lever"] == "addi r34,r52,28"
    assert "unsupported_source_span_family" not in continuation
    assert continuation["attempted_targets"] == {"34": 25}
    assert continuation["protected_targets"] == {"44": 25}
    assert continuation["compiled"] == 77
    assert continuation["progress_hits"] == 0
    assert continuation["missing_evidence"] == [
        "target-only addi/copy-product source resolver evidence"
    ]
    assert any(
        "target-only addi/copy-product source resolver evidence" in step
        for step in result["next_steps"]
    )


def test_target_only_addi_copy_product_resolver_terminal_evidence(
    tmp_path,
):
    force = _force_match()
    force["force_vector"] = "class0:ig34:phys=r25,class0:ig44:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["target_ig"] = 34
    delta["missing_virtuals"][0]["source"] = {
        "kind": "implicit-temp",
        "expression": "addi r34,r52,28",
        "confidence": "pcode-first-def",
        "source_file": None,
        "source_line": None,
        "source_col": None,
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(
                tmp_path,
                target_ig=34,
                blocker_ig=44,
            ),
            _target_only_simplify_exhausted(force_phys={"34": 25, "44": 25}),
            _target_only_addi_copy_product_resolver(),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "target-only-backprojection-source-probe-continuation-terminal"
    )
    continuation = result[
        "target_only_backprojection_source_probe_continuation"
    ]
    assert continuation["status"] == "terminal-non-source-visible"
    assert continuation["complete"] is True
    assert continuation["terminal_blocker"] == (
        "addi-copy-product-operands-not-source-visible"
    )
    assert [
        entry["expression"] for entry in continuation["copy_product_chain"]
    ] == [
        "mr r34,r37",
        "addi r37,r52,28",
        "add r44,r52,r64",
    ]
    assert continuation["copy_product_chain"][2]["protected"] is True
    assert [
        variant["score"]
        for variant in continuation["source_visible_variants"]
    ] == [266, 626]
    assert continuation["attempted_targets"] == {"34": 25}
    assert continuation["protected_targets"] == {"44": 25}
    assert continuation["final_force_phys"] == {"34": 25, "44": 25}


def test_allocator_ceiling_text_lists_addi_copy_product_resolver_facts(
    tmp_path,
):
    force = _force_match()
    force["force_vector"] = "class0:ig34:phys=r25,class0:ig44:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["target_ig"] = 34
    delta["missing_virtuals"][0]["source"] = {
        "kind": "implicit-temp",
        "expression": "addi r34,r52,28",
        "confidence": "pcode-first-def",
    }
    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(
                tmp_path,
                target_ig=34,
                blocker_ig=44,
            ),
            _target_only_simplify_exhausted(force_phys={"34": 25, "44": 25}),
            _target_only_addi_copy_product_resolver(),
        ],
        function="fn_test",
    )

    text = render_allocator_ceiling_text(result)

    assert "target-only source-probe continuation:" in text
    assert "terminal-non-source-visible" in text
    assert "addi-copy-product-operands-not-source-visible" in text
    assert "copy-product chain:" in text
    assert "ig34 mr r34,r37" in text
    assert "ig37 addi r37,r52,28" in text
    assert "ig44 add r44,r52,r64 protected" in text
    assert "source-visible variant scores: 266/626" in text


def test_target_only_addi_source_probe_waits_for_continuation_evidence(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["source"] = {
        "kind": "implicit-temp",
        "expression": "addi r40,r52,28",
        "confidence": "pcode-first-def",
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    continuation = result[
        "target_only_backprojection_source_probe_continuation"
    ]
    assert continuation["status"] == "incomplete"
    assert continuation["missing_evidence"] == [
        "matching target-only retained source-probe exhaustion"
    ]


def test_target_only_addi_rejects_unrelated_continuation_force_map(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["source"] = {
        "kind": "implicit-temp",
        "expression": "addi r40,r52,28",
        "confidence": "pcode-first-def",
    }
    unrelated_exhaustion = _target_only_simplify_exhausted()
    unrelated_exhaustion["residual_force_phys"] = {"999": 31}
    unrelated_exhaustion["force_phys"] = {"999": 31}

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
            unrelated_exhaustion,
        ],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    continuation = result[
        "target_only_backprojection_source_probe_continuation"
    ]
    assert continuation["complete"] is False
    assert continuation["final_force_phys"] == {"40": 25}


def test_target_only_addi_resolver_still_requires_simplify_exhaustion(
    tmp_path,
):
    force = _force_match()
    force["force_vector"] = "class0:ig34:phys=r25,class0:ig44:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["target_ig"] = 34
    delta["missing_virtuals"][0]["source"] = {
        "kind": "implicit-temp",
        "expression": "addi r34,r52,28",
        "confidence": "pcode-first-def",
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(
                tmp_path,
                target_ig=34,
                blocker_ig=44,
            ),
            _target_only_addi_copy_product_resolver(),
        ],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert (
        result["terminal_reason"]
        == "target-only-allocator-rotation-backprojection"
    )
    continuation = result[
        "target_only_backprojection_source_probe_continuation"
    ]
    assert continuation["status"] == "incomplete"
    assert continuation["complete"] is False
    assert continuation["missing_evidence"] == [
        "matching target-only retained source-probe exhaustion"
    ]


def test_target_only_allocator_ceiling_accepts_terminal_backprojection(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"

    result = classify_allocator_ceiling(
        [
            _bare_delta(),
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert (
        result["terminal_reason"]
        == "target-only-allocator-rotation-backprojection-terminal"
    )
    backprojection = result["target_only_allocator_backprojection"]
    assert backprojection["status"] == "terminal-non-source-expressible"
    assert backprojection["divergences"][0]["target_ig"] == 40
    assert backprojection["source_levers"] == []


def test_target_only_c2_sticky_pool_attribution_uses_retained_lanes(tmp_path):
    result = classify_allocator_ceiling(
        [
            {
                "function": "fn_test",
                "status": "practical-ceiling",
                "source_shape_exhausted": True,
                "wrong_register_exhausted": True,
                "node_set_delta": _bare_delta(),
                "force_vector": {
                    "ran": True,
                    "union_status": "match",
                    "returncode": 0,
                },
                "target_only_allocator_backprojection": {
                    "status": "terminal-non-source-expressible",
                    "force_targets": [
                        {
                            "class_id": 1,
                            "ig_idx": 37,
                            "desired_phys": 26,
                            "register": "f26",
                        },
                        {
                            "class_id": 1,
                            "ig_idx": 32,
                            "desired_phys": 26,
                            "register": "f26",
                        },
                    ],
                    "divergences": [
                        {
                            "class_id": 1,
                            "case": "C2",
                            "target_ig": 37,
                            "target_phys": 26,
                            "baseline_phys": 27,
                            "iter_idx": 27,
                            "local_target": (
                                "change how many nonvolatiles dispense before X"
                            ),
                            "force_phys": {"37": 26, "32": 26},
                        }
                    ],
                    "source_levers": [],
                    "missing_evidence": [],
                },
                "missing_evidence": [],
            },
            _target_live_range_fpr_interference_exhausted(),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "target-only-c2-sticky-pool-source-attribution-terminal"
    )
    attribution = result["target_only_c2_sticky_pool_attribution"]
    assert attribution["complete"] is True
    assert attribution["target_ig"] == 37
    assert attribution["target_phys"] == 26
    assert attribution["source_expressions"][:3] == [
        "row_offset_adj",
        "target_repair_scalar_duplicate_ig37_probe",
        "col_offset",
    ]
    assert attribution["upstream_virtuals"] == [32, 37]
    assert attribution["lane_count"] == 1
    assert attribution["evaluated_probe_count"] == 3
    assert attribution["exact_count"] == 0


def test_target_only_c2_sticky_pool_requires_protected_force_map(tmp_path):
    retained = _target_live_range_fpr_interference_exhausted()
    summary = retained["validation_summary"][
        "retained_case_c_target_live_range_repair_summary"
    ]
    summary["protected_targets"] = {"31": 26}

    result = classify_allocator_ceiling(
        [
            {
                "function": "fn_test",
                "status": "practical-ceiling",
                "source_shape_exhausted": True,
                "wrong_register_exhausted": True,
                "node_set_delta": _bare_delta(),
                "force_vector": {
                    "ran": True,
                    "union_status": "match",
                    "returncode": 0,
                },
                "target_only_allocator_backprojection": {
                    "status": "terminal-non-source-expressible",
                    "force_targets": [
                        {
                            "class_id": 1,
                            "ig_idx": 37,
                            "desired_phys": 26,
                            "register": "f26",
                        },
                        {
                            "class_id": 1,
                            "ig_idx": 32,
                            "desired_phys": 26,
                            "register": "f26",
                        },
                    ],
                    "divergences": [
                        {
                            "class_id": 1,
                            "case": "C2",
                            "target_ig": 37,
                            "target_phys": 26,
                            "baseline_phys": 27,
                            "iter_idx": 27,
                            "local_target": (
                                "change how many nonvolatiles dispense before X"
                            ),
                            "force_phys": {"37": 26, "32": 26},
                        }
                    ],
                    "source_levers": [],
                    "missing_evidence": [],
                },
                "missing_evidence": [],
            },
            retained,
        ],
        function="fn_test",
    )

    attribution = result["target_only_c2_sticky_pool_attribution"]
    assert attribution["complete"] is False
    assert attribution["missing_evidence"] == [
        "matching retained sticky-pool source attribution exhaustion"
    ]


def test_target_only_allocator_ceiling_rejects_stale_forced_pcdump(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["source"] = {
        "kind": "local",
        "expression": "target_value",
    }
    pcdump_input = _target_only_backprojection_input(tmp_path)
    pcdump_input["forced_pcdump"] = pcdump_input["natural_pcdump"]

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            pcdump_input,
        ],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert "forced pcdump must differ" in result["missing_evidence"][0]
    assert result["target_only_allocator_backprojection"]["status"] == "incomplete"


def test_target_only_allocator_ceiling_ignores_failed_force_vectors(tmp_path):
    stale_force = _force_match()
    stale_force["force_vector_verify"]["ran"] = False
    stale_force["force_vector"] = "class0:ig40:phys=r25"
    valid_force = _force_match()

    result = classify_allocator_ceiling(
        [
            _bare_delta(),
            stale_force,
            valid_force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "target-only-allocator-rotation"
    assert result["target_only_allocator_backprojection"]["status"] == "not-present"
    assert result["target_only_allocator_backprojection"]["force_targets"] == []


def test_target_only_allocator_ceiling_ignores_failed_force_pcdumps(tmp_path):
    valid_force = _force_match()
    valid_force["force_vector"] = "class0:ig40:phys=r25"
    stale_force = _force_match()
    stale_force["force_vector_verify"]["ran"] = False
    stale_force["force_vector"] = "class0:ig40:phys=r25"
    pcdump_input = _target_only_backprojection_input(tmp_path)
    stale_force["pcdump"] = pcdump_input.pop("forced_pcdump")

    result = classify_allocator_ceiling(
        [
            _bare_delta(),
            stale_force,
            valid_force,
            _node_wrong(),
            _transform_negative(),
            pcdump_input,
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "target-only-allocator-rotation"
    assert (
        result["target_only_allocator_backprojection"]["status"]
        == "missing-pcdump-evidence"
    )
    assert (
        "forced pcdump"
        in result["target_only_allocator_backprojection"]["missing_evidence"]
    )


def test_target_only_allocator_ceiling_does_not_use_unrelated_source(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["target_ig"] = 41
    delta["missing_virtuals"][0]["source"] = {
        "kind": "local",
        "expression": "unrelated_value",
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert (
        result["terminal_reason"]
        == "target-only-allocator-rotation-backprojection-terminal"
    )
    assert result["target_only_allocator_backprojection"]["source_levers"] == []


def test_target_only_allocator_ceiling_does_not_use_nondivergent_target_source(
    tmp_path,
):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25,class0:ig50:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["target_ig"] = 50
    delta["missing_virtuals"][0]["source"] = {
        "kind": "local",
        "expression": "source_for_50_only",
    }

    result = classify_allocator_ceiling(
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert (
        result["terminal_reason"]
        == "target-only-allocator-rotation-backprojection-terminal"
    )
    backprojection = result["target_only_allocator_backprojection"]
    assert backprojection["divergences"][0]["target_ig"] == 40
    assert backprojection["source_levers"] == []


def test_mixed_missing_target_node_exhaustion_counts_as_negative_proof():
    result = classify_allocator_ceiling(
        [
            _solve_delta(),
            _force_match(),
            _node_wrong_missing_target_exhausted(),
            _transform_negative(),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["wrong_register_exhausted"] is True
    assert result["node_set_exhaustion"]["complete"] is True
    assert (
        result["node_set_exhaustion"]["terminal_reason"]
        == "wrong-register-or-missing-target"
    )
    assert not any(
        "node-set-split exhaustive all-wrong-register evidence" in entry
        for entry in result["missing_evidence"]
    )


def test_mixed_missing_target_node_exhaustion_removes_legacy_missing_item():
    result = classify_allocator_ceiling(
        [_node_wrong_missing_target_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["wrong_register_exhausted"] is True
    assert result["node_set_exhaustion"]["objective_counts"] == {
        "wrong-register": 7,
        "missing-target": 1,
    }
    assert "node-set-split exhaustive all-wrong-register evidence" not in (
        "\n".join(result["missing_evidence"])
    )


def test_positive_proof_wins_over_negative_evidence():
    improved = dict(_node_wrong(), status="improved", best_checkdiff_delta=0.25)

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), improved, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert result["positive_proofs"]
    assert result["exit_code"] == 0


def test_bounded_transform_omitted_probe_blocks_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["omitted_count"] = 1

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "transform-corpus omitted 1 node-set probe" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_bounded_transform_capped_probe_blocks_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["capped_count"] = 1

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "transform-corpus capped 1 node-set probe" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_skipped_unbindable_transform_evidence_does_not_block_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["skipped_count"] = 2

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["skipped_source_evidence_count"] == 2


def test_missing_force_vector_is_incomplete_not_ceiling():
    result = classify_allocator_ceiling(
        [_solve_delta(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert "force-phys verification with union status match" in result["missing_evidence"]
    assert result["exit_code"] == 3


def test_force_vector_match_without_run_is_incomplete():
    force = _force_match()
    force["force_vector_verify"]["ran"] = False

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["ran"] is False
    assert result["force_vector"]["union_status"] == "match"
    assert "force-phys verification with union status match" in result["missing_evidence"]


def test_force_vector_prefers_ran_match_over_stale_match():
    stale_force = _force_match()
    stale_force["force_vector_verify"]["ran"] = False
    valid_force = _force_match()

    result = classify_allocator_ceiling(
        [_solve_delta(), stale_force, valid_force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["force_vector"]["ran"] is True
    assert result["force_vector"]["union_status"] == "match"
    assert result["missing_evidence"] == []


def test_force_vector_fallback_prefers_executed_no_match_over_stale_match():
    stale_force = _force_match()
    stale_force["force_vector_verify"]["ran"] = False
    executed_force = _force_match()
    executed_force["force_vector_verify"]["union"]["status"] = "no_match"

    result = classify_allocator_ceiling(
        [_solve_delta(), stale_force, executed_force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["ran"] is True
    assert result["force_vector"]["union_status"] == "no_match"


def test_generic_force_vector_no_match_without_draw_frontier_is_incomplete():
    force = _force_match()
    force["force_vector_verify"]["union"]["status"] = "no_match"

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["union_status"] == "no_match"
    assert "force-phys verification with union status match" in result["missing_evidence"]


def test_live_implicit_temp_copy_survived_stack_is_practical_ceiling_without_force_vector_or_wrong_register():
    result = classify_allocator_ceiling(
        [
            _sort_live_implicit_temp_node_delta(),
            _sort_live_select_order_materialized_implicit_temps(),
            _sort_node_set_split_zero_bindable(),
            _sort_copy_survived_terminal(),
        ],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "residual-case-c-source-repair-exhausted"
    assert result["source_shape_exhausted"] is True
    assert result["wrong_register_exhausted"] is False
    assert result["force_vector"]["ran"] is False
    assert result["missing_evidence"] == []
    residual = result["residual_case_c_source_repair"]
    assert residual["complete"] is True
    assert residual["terminal_stack"] == "live-implicit-temp-copy-survived"
    assert residual["copy_survived_repair"]["status"] == "terminal-blocker"
    assert residual["copy_survived_repair"]["from_virtual"] == 34
    assert residual["copy_survived_repair"]["to_virtual"] == 41
    assert residual["node_set_unsplittable_frontier"]["reason"] == (
        "zero-bindable-implicit-temp-frontier"
    )
    assert not any("Collect missing evidence" in step for step in result["next_steps"])

    text = render_allocator_ceiling_text(result)
    assert "live implicit-temp terminal stack:" in text
    assert "zero-bindable node-set split" in text
    assert "copy-survived: ig34->ig41" in text


def test_live_implicit_temp_stack_without_copy_survived_terminal_remains_incomplete():
    result = classify_allocator_ceiling(
        [
            _sort_live_implicit_temp_node_delta(),
            _sort_live_select_order_materialized_implicit_temps(),
            _sort_node_set_split_zero_bindable(),
        ],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "incomplete"
    assert result["terminal_reason"] == "missing-required-evidence"
    assert result["residual_case_c_source_repair"]["complete"] is False
    gaps = "\n".join(
        [
            *result["missing_evidence"],
            *result["next_steps"],
            *result["residual_case_c_source_repair"]["missing_evidence"],
        ]
    )
    assert "copy-survived pointer-reset terminal evidence" in gaps


def test_zero_bindable_node_set_split_is_not_all_wrong_register_exhaustion():
    result = classify_allocator_ceiling(
        [
            _sort_live_implicit_temp_node_delta(),
            _sort_node_set_split_zero_bindable(),
        ],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["wrong_register_exhausted"] is False
    assert result["node_set_exhaustion"]["complete"] is False
    assert result["node_set_exhaustion"]["terminal_reason"] is None


def test_function_mismatch_rejected_in_nested_payload():
    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_solve_delta("other_fn"), _force_match(), _node_wrong()],
            function="fn_test",
        )


def test_unscoped_evidence_rejected():
    unscoped = {
        "status": "exhausted",
        "wrong_register_exhausted": True,
    }

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([unscoped], function="fn_test")


def test_unscoped_sort_protected_recombine_accepts_only_concrete_target_assignments():
    result = classify_allocator_ceiling(
        [_sort_protected_loss_recombine_artifact()],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    meta = result["retained_frontiers_meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    synthesis = meta["terminal_proof"]["source_family_synthesis"]
    assert synthesis["protected_structural_synthesis"]["required_assignments"] == (
        _sort_force()
    )
    assert "lower-drift-candidates-lost-protected-assignments" in (
        synthesis["terminal_blockers"]
    )
    assert synthesis["ranked_candidates"][0]["source_hunks"]

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [
                _sort_protected_loss_recombine_artifact(
                    required_assignments={"34": 27}
                )
            ],
            function="mnDiagram_SortNamesByKOs",
        )


def test_allocator_ceiling_consumes_direct_sort_target_live_range_as_retained_meta():
    result = classify_allocator_ceiling(
        [_target_live_range_blocker_chain_exhausted("mnDiagram_SortNamesByKOs")],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    meta = result["retained_frontiers_meta_ceiling"]
    assert meta["status"] == "terminal-current-source-shape-ceiling"
    assert meta["terminal_proof"]["allocator_facts"]


def test_allocator_ceiling_accepts_full_retained_frontiers_aggregate_as_meta_ceiling():
    result = classify_allocator_ceiling(
        [_retained_frontiers_aggregate()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    assert result["source_shape_exhausted"] is True
    assert result["missing_evidence"] == []
    assert (
        result["retained_frontiers_meta_ceiling"]["terminal_proof"]["status"]
        == "complete"
    )


def test_allocator_ceiling_accepts_extracted_retained_frontiers_function_entry():
    result = classify_allocator_ceiling(
        [_retained_frontiers_function_entry()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["missing_evidence"] == []
    assert result["retained_frontiers_meta_ceiling"]["source_shape_exhausted"] is True


def test_allocator_ceiling_draw_meta_ceiling_preserves_expression_source_class():
    result = classify_allocator_ceiling(
        [_draw_issue998_retained_frontiers_aggregate()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    current = result["current_ceiling"]
    assert current["source_spans"]
    assert current["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS
    assert current["next_unsupported_source_model"] == DRAW_COUPLED_UNSUPPORTED_MODEL
    actuals = {row["virtual"]: row["actual"] for row in current["allocator_facts"]}
    assert actuals.items() >= {32: 26, 37: 28, 46: 1}.items()

    text = render_allocator_ceiling_text(result)
    assert DRAW_COUPLED_UNSUPPORTED_CLASS in text
    assert DRAW_COUPLED_UNSUPPORTED_MODEL in text
    assert "col_offset" in text


def test_allocator_ceiling_post_source_context_terminal_suppresses_stale_dimension():
    result = classify_allocator_ceiling(
        [_draw_issue1040_post_whole_terminal_discovery()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert current["next_unsupported_source_model"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
    )
    assert current.get("next_unsupported_source_dimension") != (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert current["exhausted_source_dimension"] == (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert DRAW_POST_SOURCE_CONTEXT_DIMENSION in current["exhausted_dimensions"]
    best = current["candidate_scores"][0]
    assert best["candidate_id"] == (
        "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
    )
    assert best["target_score"]["matched"] == 1
    assert best["expression_score"]["matched"] == 1
    assert any(
        DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL in step
        or DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_draw_post_all_known_actionable_outranks_stale_handoff():
    result = classify_allocator_ceiling(
        [
            _draw_stale_post_source_context_actionable_discovery(),
            _draw_post_all_known_retained_frontiers_aggregate(actionable=True),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == "retained-frontiers-next-source-actionable-lane"
    next_frontier = result["retained_frontiers_meta_ceiling"]["next_frontier"]
    assert next_frontier["frontier_id"] == "draw-post-all-known-candidate"
    assert next_frontier["continuation"]["route"] == DRAW_POST_ALL_KNOWN_DIMENSION
    assert result["post_source_context_next_dimension"] is None
    assert any(
        "post-all-known frontiers source-context hypothesis" in step
        for step in result["next_steps"]
    )
    text = render_allocator_ceiling_text(result)
    assert f"next lane dimension: {DRAW_POST_ALL_KNOWN_DIMENSION}" in text


def test_allocator_ceiling_draw_post_all_known_terminal_suppresses_stale_discovery():
    result = classify_allocator_ceiling(
        [
            _draw_stale_post_source_context_actionable_discovery(),
            _draw_post_all_known_retained_frontiers_aggregate(),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_ALL_KNOWN_FINAL_FAMILY
    )
    assert current["next_unsupported_source_model"] == DRAW_POST_ALL_KNOWN_FINAL_MODEL
    assert result["post_source_context_next_dimension"] is None
    assert not any(
        "post-source-context-next-dimension JSON" in step
        for step in result["next_steps"]
    )
    text = render_allocator_ceiling_text(result)
    assert "post-all-known source-context hypothesis: present" in text
    assert DRAW_POST_ALL_KNOWN_FINAL_FAMILY in text


def test_allocator_ceiling_draw_product_translate_actionable_outranks_post_all_known():
    result = classify_allocator_ceiling(
        [
            _draw_post_all_known_retained_frontiers_aggregate(actionable=True),
            _draw_product_translate_retained_frontiers_aggregate(actionable=True),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "actionable"
    next_frontier = result["retained_frontiers_meta_ceiling"]["next_frontier"]
    assert next_frontier["frontier_id"] == "draw-product-translate-candidate"
    assert next_frontier["continuation"]["route"] == DRAW_PRODUCT_TRANSLATE_DIMENSION
    assert any(
        "product/translate expression-graph lane" in step
        for step in result["next_steps"]
    )
    text = render_allocator_ceiling_text(result)
    assert f"next lane dimension: {DRAW_PRODUCT_TRANSLATE_DIMENSION}" in text


def test_allocator_ceiling_draw_product_translate_terminal_suppresses_post_all_known():
    result = classify_allocator_ceiling(
        [
            _draw_post_all_known_retained_frontiers_aggregate(),
            _draw_product_translate_retained_frontiers_aggregate(),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY
    )
    assert current["next_unsupported_source_model"] == (
        DRAW_PRODUCT_TRANSLATE_FINAL_MODEL
    )
    text = render_allocator_ceiling_text(result)
    assert "product/translate expression graph: present" in text
    assert DRAW_PRODUCT_TRANSLATE_FINAL_FAMILY in text


def test_allocator_ceiling_reports_stack_clean_no_anchor_recovery_actionable():
    result = classify_allocator_ceiling(
        [_draw_stack_clean_no_anchor_retained_frontiers_aggregate(actionable=True)],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "actionable"
    next_frontier = result["retained_frontiers_meta_ceiling"]["next_frontier"]
    assert next_frontier["continuation"]["route"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert any(
        "stack-clean/no-anchor recovery" in step
        for step in result["next_steps"]
    )
    assert any("build/stack-clean-seed.pcdump.txt" in step for step in result["next_steps"])
    assert any("delta=8" in step for step in result["next_steps"])
    text = render_allocator_ceiling_text(result)
    assert f"next lane dimension: {DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}" in text


def test_allocator_ceiling_stack_clean_terminal_suppresses_consumed_actionable_seed():
    result = classify_allocator_ceiling(
        [
            _draw_stack_clean_no_anchor_retained_frontiers_aggregate(
                actionable=True
            ),
            _draw_stack_clean_no_anchor_terminal(),
        ],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    retained_meta = result["retained_frontiers_meta_ceiling"]
    assert retained_meta["status"] == "terminal-current-source-shape-ceiling"
    assert retained_meta["next_frontier"] is None
    assert retained_meta["ranked_next_lanes"] == []
    current = result["current_ceiling"]
    assert current["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert current["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert not any(
        "Continue stack-clean/no-anchor recovery" in step
        for step in result["next_steps"]
    )
    assert any(
        "Stack-clean/no-anchor recovery is terminal" in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_reports_draw_helper_boundary_handoff_actionable():
    result = classify_allocator_ceiling(
        [_draw_helper_boundary_retained_frontiers_aggregate()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "actionable"
    next_frontier = result["retained_frontiers_meta_ceiling"]["next_frontier"]
    assert next_frontier["continuation"]["route"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert any(
        "helper/inline-boundary handoff" in step
        for step in result["next_steps"]
    )
    assert any(
        f"Unsupported source expression class: {DRAW_COUPLED_UNSUPPORTED_CLASS}"
        in step
        for step in result["next_steps"]
    )
    assert any(
        "Representative pcdump: build/draw/helper-boundary-seed.pcdump.txt"
        in step
        for step in result["next_steps"]
    )
    assert any(
        f"Next unsupported source model: {DRAW_COUPLED_UNSUPPORTED_MODEL}"
        in step
        for step in result["next_steps"]
    )
    text = render_allocator_ceiling_text(result)
    assert f"next lane dimension: {DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION}" in text


def test_allocator_ceiling_reports_draw_helper_boundary_terminal_blocker():
    result = classify_allocator_ceiling(
        [_draw_helper_boundary_terminal_retained_frontiers_aggregate()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["terminal_blocker"] == DRAW_HELPER_BOUNDARY_TERMINAL_REASON
    assert current["exhausted_source_dimension"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert current["next_unsupported_source_family"] == (
        DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    )
    assert current["next_unsupported_source_model"] == (
        DRAW_HELPER_BOUNDARY_FINAL_MODEL
    )
    assert "next_unsupported_source_dimension" not in current
    synthesis = current["source_family_synthesis"]
    assert synthesis["next_unsupported_source_family"] == (
        DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    )
    assert any(
        row["dimension_id"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        for row in synthesis["exhausted_dimensions"]
    )
    assert any(
        "helper/inline-boundary handoff is terminal" in step
        for step in result["next_steps"]
    )
    assert any(
        DRAW_HELPER_BOUNDARY_TERMINAL_REASON in step
        for step in result["next_steps"]
    )
    assert any(
        DRAW_HELPER_BOUNDARY_REJECTION_REASON in step
        for step in result["next_steps"]
    )

    text = render_allocator_ceiling_text(result)
    assert "helper/inline-boundary handoff: terminal" in text
    assert f"helper-boundary blocker: {DRAW_HELPER_BOUNDARY_TERMINAL_REASON}" in text
    assert DRAW_HELPER_BOUNDARY_REJECTION_REASON in text
    assert DRAW_HELPER_BOUNDARY_FINAL_FAMILY in text
    assert f"next unsupported source dimension: {DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION}" not in text


def test_allocator_ceiling_reports_stack_clean_no_anchor_terminal_ceiling():
    result = classify_allocator_ceiling(
        [_draw_stack_clean_no_anchor_retained_frontiers_aggregate()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert current["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert current["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert current["stack_clean_no_anchor_evidence"]["seed_candidate_id"] == (
        _draw_stack_clean_no_anchor_evidence()["seed_candidate_id"]
    )
    assert any(
        "Stack-clean/no-anchor recovery is terminal" in step
        for step in result["next_steps"]
    )
    assert any(
        "Active next modeled source dimension: "
        f"{DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION}" in step
        for step in result["next_steps"]
    )
    text = render_allocator_ceiling_text(result)
    assert "stack-clean/no-anchor recovery: terminal" in text
    assert DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION in text


def test_allocator_ceiling_promotes_post_stack_source_shape_over_stack_clean_recovery():
    result = classify_allocator_ceiling(
        [_draw_post_stack_clean_with_stale_stack_aggregate()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert current["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert current["post_stack_clean_no_anchor_evidence"]
    assert any(
        "Post-stack-clean/no-anchor source-shape synthesis is terminal" in step
        for step in result["next_steps"]
    )
    assert any(
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY in step
        for step in result["next_steps"]
    )
    assert not any(
        "Stack-clean/no-anchor recovery is terminal" in step
        for step in result["next_steps"]
    )
    text = render_allocator_ceiling_text(result)
    assert "post-stack-clean/no-anchor source-shape: terminal" in text
    assert DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY in text


def test_allocator_ceiling_current_ceiling_keeps_post_stack_terminal_over_post_product_recovery(
    tmp_path,
):
    old_aggregate = {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": [],
                "terminal_frontiers": [
                    _draw_post_stack_clean_no_anchor_source_shape_terminal()
                ],
                "next_frontier": None,
                "summary": {"unexhausted_count": 0, "terminal_count": 1},
            }
        ],
    }
    old_path = _write_json(tmp_path / "old-post-stack.json", old_aggregate)
    new_terminal = _draw_stack_clean_no_anchor_terminal()
    new_terminal["terminal_reason"] = (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    )
    new_terminal["source_model_proof"]["terminal_reason"] = (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    )
    new_path = _write_json(
        tmp_path / "new-post-product-terminal.json",
        new_terminal,
    )
    os.utime(old_path, (1000, 1000))
    os.utime(new_path, (2000, 2000))
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[old_path, new_path],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert current["terminal_reason"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert current["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )


def test_allocator_ceiling_current_ceiling_keeps_post_stack_loop_callsite_terminal(
    tmp_path,
):
    old_path = _write_json(
        tmp_path / "old-post-stack.json",
        _draw_post_stack_clean_no_anchor_source_shape_terminal(),
    )
    new_path = _write_json(
        tmp_path / "new-post-stack-loop-callsite.json",
        _draw_post_stack_loop_callsite_source_context_terminal(),
    )
    os.utime(old_path, (1000, 1000))
    os.utime(new_path, (2000, 2000))
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[old_path, new_path],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert current["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    assert current["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert current["next_unsupported_source_family"] != (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_allocator_ceiling_draw_post_row_offset_owner_lifetime_actionable_lane():
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
    }
    meta = {
        "kind": "retained-frontiers-meta-ceiling",
        "function": "mnDiagram_DrawCellNumber",
        "status": "actionable",
        "retained_frontiers_status": "actionable",
        "next_frontier": lane,
        "ranked_next_lanes": [lane],
        "closed_families": [],
        "terminal_groups": [],
    }
    retained_payload = {
        "status": "actionable",
        "functions": [
            {
                "function": "mnDiagram_DrawCellNumber",
                "frontiers": [lane],
                "terminal_frontiers": [],
                "next_frontier": lane,
                "summary": {"unexhausted_count": 1, "terminal_count": 0},
                "meta_ceiling": meta,
            }
        ],
        "next_frontier": lane,
        "meta_ceiling": meta,
    }

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == "retained-frontiers-next-source-actionable-lane"
    continuation = result["next_frontier"]["continuation"]
    assert continuation["source_retained"] == candidate["source_retained"]
    assert continuation["pcdump_path"] == candidate["pcdump_path"]
    assert continuation["source_hunks"] == candidate["source_hunks"]
    assert continuation["target_score"] == candidate["target_score"]
    assert continuation["expression_score"] == candidate["expression_score"]
    assert any("source-family-continuation" in step for step in result["next_steps"])


def test_allocator_ceiling_draw_post_row_offset_owner_lifetime_terminal_suppresses_owner_split():
    retained = {
        "candidate_id": (
            "draw-post-row-offset-owner-expression-lifetime-"
            "row-offset-adj-callsite-owner"
        ),
        "dimension_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
        "source_retained": "build/draw/post-row-offset-lifetime.c",
        "pcdump_path": "build/draw/post-row-offset-lifetime.pcdump.txt",
        "source_hunks": [{"hunk_id": "post-row-offset-lifetime"}],
        "target_score": {"matched": 1, "targeted": 3},
        "expression_score": {"matched": 0, "targeted": 3},
    }
    proof = {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "terminal_reason": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON,
        "terminal_blocker": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER,
        "next_unsupported_source_family": (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL
        ),
        "exhausted_source_dimension": (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        ),
        "candidate_scores": [retained],
        "retained_scored_probes": [retained],
        "source_family_synthesis": {
            "attempted_equivalence_classes": [
                DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION,
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
            ],
            "exhausted_dimensions": [
                {
                    "dimension_id": (
                        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION
                    ),
                    "status": "scored-terminal",
                },
                {
                    "dimension_id": (
                        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
                    ),
                    "status": "scored-terminal",
                    "exhaustion_reason": (
                        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
                    ),
                },
            ],
            "exhausted_source_dimension": (
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
            ),
            "next_unsupported_source_family": (
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL
            ),
            "retained_scored_probes": [retained],
            "source_hunks_by_candidate": [
                {
                    "candidate_id": retained["candidate_id"],
                    "dimension_id": (
                        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
                    ),
                    "source_hunks": retained["source_hunks"],
                }
            ],
        },
    }
    owner_group = {
        "family_id": DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_DIMENSION,
        "next_unsupported_source_family": (
            DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
        ),
    }
    lifetime_group = {
        "family_id": DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION,
        "next_unsupported_source_family": (
            DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
        ),
    }
    meta = {
        "kind": "retained-frontiers-meta-ceiling",
        "function": "mnDiagram_DrawCellNumber",
        "status": "terminal-current-source-shape-ceiling",
        "retained_frontiers_status": "all-known-frontiers-exhausted",
        "next_frontier": None,
        "ranked_next_lanes": [],
        "terminal_proof": proof,
        "terminal_groups": [owner_group, lifetime_group],
        "closed_families": [],
    }
    result = classify_allocator_ceiling(
        [meta],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    current = result["current_ceiling"]
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    )
    assert current["exhausted_source_dimension"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    assert current["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
    )


def test_allocator_ceiling_prefers_newer_sort_terminal_over_older_deeper_terminal(
    tmp_path,
):
    stale_cross_tu = _write_json(
        tmp_path / "sort-cross-tu.json",
        _sort_source_model_terminal_artifact(
            dimension=SORT_CROSS_TU_DIMENSION,
            family=SORT_POST_CROSS_TU_FAMILY,
            model=(
                "Sort cross-TU symbol/linkage source-context synthesis "
                "exhausted; no modeled source-actionable family remains."
            ),
            candidate_prefix="post-meta-sort-cross-tu-",
        ),
    )
    current_whole_function = _write_json(
        tmp_path / "sort-whole-function.json",
        _sort_source_model_terminal_artifact(
            dimension=SORT_WHOLE_FUNCTION_DIMENSION,
            family=SORT_HELPER_DATA_LAYOUT_FAMILY,
            model=(
                "Sort whole-function control/data-flow source-model synthesis "
                "exhausted; helper/data-layout source context is the next "
                "unsupported family."
            ),
            candidate_prefix="post-meta-sort-whole-function-",
        ),
    )
    os.utime(stale_cross_tu, (1000, 1000))
    os.utime(current_whole_function, (2000, 2000))
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale_cross_tu, current_whole_function],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        SORT_HELPER_DATA_LAYOUT_FAMILY
    )
    assert result["current_ceiling"]["next_unsupported_source_family"] != (
        SORT_POST_CROSS_TU_FAMILY
    )
    assert any(
        SORT_HELPER_DATA_LAYOUT_FAMILY in step
        for step in result["next_steps"]
    )
    assert not any(
        f"Next unsupported source family: {SORT_POST_CROSS_TU_FAMILY}" in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_reports_sort_cross_tu_no_modeled_terminal_details(
    tmp_path,
):
    terminal = _write_json(
        tmp_path / "sort-cross-tu-no-modeled.json",
        _sort_cross_tu_no_modeled_terminal_artifact(),
    )
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[terminal],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["next_frontier"] is None
    current = result["current_ceiling"]
    assert current["next_unsupported_source_model"] == SORT_CROSS_TU_MODEL
    assert current["next_unsupported_source_family"] == SORT_POST_CROSS_TU_FAMILY
    blockers = current["source_family_synthesis"]["terminal_blockers"]
    assert SORT_CROSS_TU_NO_MODELED_BLOCKER in blockers
    assert any(SORT_CROSS_TU_NO_MODELED_BLOCKER in step for step in result["next_steps"])


def test_allocator_ceiling_current_ceiling_uses_post_broader_inline_boundary_terminal(
    tmp_path,
):
    broader = _write_json(
        tmp_path / "sort-broader.json",
        _sort_post_cross_tu_broader_natural_terminal_artifact(),
    )
    post_broader = _write_json(
        tmp_path / "sort-post-broader.json",
        _sort_post_broader_inline_boundary_terminal_artifact(),
    )
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[broader, post_broader],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY
    )
    assert any(
        SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_consumes_retained_broader_terminal_with_stale_frontier(
    tmp_path,
):
    stale = _write_json(
        tmp_path / "sort-stale-selection-swap.json",
        _sort_stale_selection_swap_terminal_with_post_inline_attempt(),
    )
    broader = _write_json(
        tmp_path / "sort-broader.json",
        _sort_post_cross_tu_broader_natural_terminal_artifact(),
    )
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[stale, broader],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_FAMILY
    )
    assert result["current_ceiling"]["next_unsupported_source_family"] != (
        SORT_POST_CROSS_TU_SOURCE_HYPOTHESIS_FAMILY
    )
    assert not any(
        "rerun sort-post-cross-tu-broader-natural-c-rewrite" in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_reports_post_broader_terminal_after_post_broader_exhaustion(
    tmp_path,
):
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[
            _write_json(
                tmp_path / "sort-post-broader.json",
                _sort_post_broader_inline_boundary_terminal_artifact(),
            )
        ],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        SORT_POST_BROADER_INLINE_BOUNDARY_FAMILY
    )


def test_allocator_ceiling_current_ceiling_uses_post_inline_boundary_selection_emission_terminal(
    tmp_path,
):
    post_broader = _write_json(
        tmp_path / "sort-post-broader.json",
        _sort_post_broader_inline_boundary_terminal_artifact(),
    )
    post_inline = _write_json(
        tmp_path / "sort-post-inline-selection-emission.json",
        _sort_post_inline_boundary_selection_emission_terminal_artifact(),
    )
    retained_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_SortNamesByKOs"],
        artifacts=[post_broader, post_inline],
    )

    result = classify_allocator_ceiling(
        [retained_payload],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "practical-ceiling"
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY
    )
    assert any(
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_FAMILY in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_stack_clean_final_beats_stale_helper_next_steps():
    result = classify_allocator_ceiling(
        [_draw_stack_clean_final_with_stale_helper_aggregate()],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    assert result["source_shape_exhausted"] is True
    current = result["current_ceiling"]
    assert current["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert current["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert current["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert current["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert not any(
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION in step
        for step in result["next_steps"]
    )
    assert not any(
        "Next unsupported source dimension: "
        f"{DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}" in step
        for step in result["next_steps"]
    )
    assert any(
        "Stack-clean/no-anchor recovery is terminal" in step
        for step in result["next_steps"]
    )
    assert any(
        "Active next modeled source dimension: "
        f"{DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION}" in step
        for step in result["next_steps"]
    )


def test_allocator_ceiling_accepts_direct_stack_clean_final_discovery():
    proof = {
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "function": "mnDiagram_DrawCellNumber",
        "status": "unsupported-source-family",
        "trigger_dimension": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "exhausted_source_dimension": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "exhausted_dimensions": [
            {"dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}
        ],
        "next_unsupported_source_family": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        ),
        "next_unsupported_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "stack_clean_no_anchor_evidence": _draw_stack_clean_no_anchor_evidence(),
    }

    result = classify_allocator_ceiling(
        [proof],
        function="mnDiagram_DrawCellNumber",
    )
    text = render_allocator_ceiling_text(result)

    assert result["status"] == "practical-ceiling"
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert any(
        "Stack-clean/no-anchor recovery is terminal" in step
        for step in result["next_steps"]
    )
    assert not any(
        "Next unsupported source dimension: "
        f"{DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}" in step
        for step in result["next_steps"]
    )
    assert "stack-clean/no-anchor recovery: terminal" in text
    assert (
        f"next unsupported source dimension: "
        f"{DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION}"
        not in text
    )


def test_allocator_ceiling_retained_frontiers_actionable_lane_returns_actionable():
    result = classify_allocator_ceiling(
        [_retained_frontiers_aggregate(actionable=True, terminal=False)],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == "retained-frontiers-next-source-actionable-lane"
    assert any("debug target score-source" in step for step in result["next_steps"])


def test_allocator_ceiling_preserves_sort_post_inline_protected_continuation_lane():
    lane = {
        "function": "mnDiagram_SortNamesByKOs",
        "frontier_id": (
            "mnDiagram_SortNamesByKOs|post-inline-protected-continuation|issue1069"
        ),
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "actionable",
        "terminal": False,
        "actionable": True,
        "rank": 1,
        "attempted_targets": {"34": 27, "44": 25},
        "protected_targets": {"34": 27, "44": 25},
        "final_force_phys": {"34": 27, "44": 25},
        "continuation": {
            "route": "sort-semantic-protected-loss-repair",
            "candidate_id": "combine-post-inline-ig34-ig44-lower-drift",
            "source_retained": (
                "build/sort/combine-post-inline-ig34-ig44-lower-drift.c"
            ),
            "pcdump_path": (
                "build/sort/combine-post-inline-ig34-ig44-lower-drift.pcdump.txt"
            ),
            "satisfied_protected_assignments": [{"ig": 44, "phys": 25}],
            "missing_protected_assignments": [{"ig": 34, "phys": 27}],
            "command": (
                "melee-agent debug target score-source "
                "build/sort/combine-post-inline-ig34-ig44-lower-drift.c "
                "--function mnDiagram_8023FC28 --json"
            ),
        },
    }
    aggregate = {
        "status": "actionable",
        "artifact_count": 1,
        "parsed_artifact_count": 1,
        "skipped_artifacts": [],
        "functions": [
            {
                "function": "mnDiagram_SortNamesByKOs",
                "frontiers": [lane],
                "terminal_frontiers": [],
                "next_frontier": lane,
                "summary": {"unexhausted_count": 1, "terminal_count": 0},
                "meta_ceiling": {
                    "kind": "retained-frontiers-meta-ceiling",
                    "function": "mnDiagram_SortNamesByKOs",
                    "status": "actionable",
                    "next_frontier": lane,
                    "ranked_next_lanes": [lane],
                },
            }
        ],
        "next_frontier": lane,
    }

    result = classify_allocator_ceiling(
        [aggregate],
        function="mnDiagram_SortNamesByKOs",
    )

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == "retained-frontiers-next-source-actionable-lane"
    retained_meta = result["retained_frontiers_meta_ceiling"]
    assert retained_meta["next_frontier"]["continuation"]["route"] == (
        "sort-semantic-protected-loss-repair"
    )
    assert retained_meta["next_frontier"]["continuation"]["source_retained"].endswith(
        ".c"
    )
    assert any("debug target score-source" in step for step in result["next_steps"])


def test_allocator_ceiling_retained_frontiers_plural_source_hunks_next_step():
    aggregate = _retained_frontiers_aggregate(terminal=False)
    source_hunks_lane = {
        "function": "fn_test",
        "frontier_id": "fn_test|post-ceiling-source-model-proof|semantic-recombine",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-meta-source-family-continuation-proof",
        "status": "actionable",
        "terminal": False,
        "actionable": False,
        "rank": 1,
        "attempted_targets": {"34": 27, "44": 25},
        "protected_targets": {"34": 27, "44": 25},
        "final_force_phys": {"34": 27, "44": 25},
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
    aggregate["status"] = "actionable"
    aggregate["functions"][0]["frontiers"] = [source_hunks_lane]
    aggregate["functions"][0]["summary"]["unexhausted_count"] = 1

    result = classify_allocator_ceiling([aggregate], function="fn_test")

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == "retained-frontiers-next-source-actionable-lane"
    assert result["retained_frontiers_meta_ceiling"]["next_frontier"][
        "continuation"
    ]["source_hunks"]
    assert any("source hunks" in step for step in result["next_steps"])


def test_allocator_ceiling_ignores_non_actionable_retained_meta_command_lane():
    aggregate = _retained_frontiers_aggregate()
    stale_lane = {
        "function": "fn_test",
        "frontier_id": "fn_test|retained-source-select-order-repair|stale",
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
            "source_retained": "build/probes/fn_test.c",
            "command": (
                "melee-agent debug target score-source build/probes/fn_test.c "
                "--function fn_test --json --retain-pcdump"
            ),
        },
    }
    aggregate["functions"][0]["frontiers"] = [stale_lane]
    aggregate["functions"][0]["summary"]["unexhausted_count"] = 1

    result = classify_allocator_ceiling([aggregate], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    assert result["current_ceiling"] is not None
    assert (
        result["retained_frontiers_meta_ceiling"]["terminal_proof"]["status"]
        == "complete"
    )
    assert not any(
        "debug target score-source" in step for step in result["next_steps"]
    )


def test_allocator_ceiling_retained_frontiers_mixed_function_scope():
    mixed = _retained_frontiers_aggregate("other_fn")
    mixed["functions"].append(_retained_frontiers_function_entry("fn_test"))

    result = classify_allocator_ceiling([mixed], function="fn_test")
    assert result["status"] == "practical-ceiling"
    assert result["retained_frontiers_meta_ceiling"]["function"] == "fn_test"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_retained_frontiers_aggregate("other_fn")],
            function="fn_test",
        )
    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_retained_frontiers_function_entry("other_fn")],
            function="fn_test",
        )


def test_allocator_ceiling_retained_frontiers_terminal_loses_to_positive():
    retained = _retained_frontiers_aggregate()
    improved = dict(_node_wrong(), status="improved", best_checkdiff_delta=0.25)

    result = classify_allocator_ceiling([retained, improved], function="fn_test")

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == "positive-proof"


def test_allocator_ceiling_retained_frontiers_terminal_loses_to_bounded():
    retained = _retained_frontiers_aggregate()
    bounded = _transform_negative()
    bounded["node_set_delta_summary"]["omitted_count"] = 1

    result = classify_allocator_ceiling([retained, bounded], function="fn_test")

    assert result["status"] == "bounded"
    assert result["terminal_reason"] == "bounded-evidence"


def test_allocator_ceiling_retained_frontiers_terminal_loses_to_expression_terminal():
    result = classify_allocator_ceiling(
        [_retained_frontiers_aggregate(), _expression_interferer_terminal()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "expression-scored-fpr-allocator-ceiling"


def test_allocator_ceiling_retained_frontiers_terminal_loses_to_target_only_terminal(
    tmp_path,
):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"

    result = classify_allocator_ceiling(
        [
            _retained_frontiers_aggregate(),
            _bare_delta(),
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "target-only-allocator-rotation-backprojection-terminal"
    )


def test_expression_interferer_terminal_is_practical_ceiling():
    result = classify_allocator_ceiling(
        [_expression_interferer_terminal()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "expression-scored-fpr-allocator-ceiling"
    assert result["source_shape_exhausted"] is True
    assert result["missing_evidence"] == []
    assert result["expression_interferer_terminal"]["complete"] is True
    assert result["backend_blockers"] == [
        {
            "class_id": 1,
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
            "mutators": [
                "expression-interferer:row_fsubs_owner_repair",
                "expression-interferer:non_satisfied_select_order",
            ],
            "source": "col_offset",
        },
        {
            "class_id": 1,
            "original_ig": 37,
            "new_ig": 37,
            "desired_phys": 26,
            "assigned_phys": 28,
            "mutators": [
                "expression-interferer:row_fsubs_owner_repair",
                "expression-interferer:non_satisfied_select_order",
            ],
            "source": "row_offset",
        },
    ]


def test_expression_interferer_terminal_without_scope_is_allowed():
    result = classify_allocator_ceiling(
        [_expression_interferer_terminal(include_scope=False)],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "expression-scored-fpr-allocator-ceiling"
    assert result["expression_interferer_terminal"]["complete"] is True


def test_expression_interferer_mismatched_source_generation_function_rejected():
    evidence = _expression_interferer_terminal()
    evidence["source_generation"]["function"] = "other_fn"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([evidence], function="fn_test")


def test_expression_interferer_terminal_missing_route_is_incomplete_with_precise_gap():
    evidence = _expression_interferer_terminal()
    evidence["post_bridge_terminal_summary"]["exhausted_routes"] = [
        "row_fsubs_owner_repair",
    ]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert result["terminal_reason"] == "missing-required-evidence"
    assert (
        "expression-interferer exhausted routes: "
        "row_fsubs_owner_repair, non_satisfied_select_order"
    ) in result["missing_evidence"]
    assert not any(
        "force-phys verification with union status match" in entry
        for entry in result["missing_evidence"]
    )


def test_expression_interferer_terminal_missing_swap_evidence_is_incomplete():
    evidence = _expression_interferer_terminal()
    del evidence["post_bridge_terminal_summary"]["evidence"]["current_paired_reg"]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert result["terminal_reason"] == "missing-required-evidence"
    assert "expression-interferer FPR swap evidence" in result["missing_evidence"]


def test_bare_node_set_delta_payload_counts_as_required_delta():
    result = classify_allocator_ceiling(
        [_bare_delta(), _force_match(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["node_set_delta"]["function"] == "fn_test"


def test_bounded_candidate_limit_blocks_ceiling():
    node = dict(_node_wrong(), stop_reason="candidate-limit")

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "candidate-limit" in " ".join(result["bounded_reasons"])
    assert result["exit_code"] == 4


def test_remote_pcdump_failure_blocks_ceiling_with_resume_command():
    command = (
        "melee-agent debug solve node-set-split --remote "
        "--max-candidates 0 --resume-summary out.json"
    )
    node = dict(
        _node_wrong(),
        stop_condition={
            "kind": "remote-pcdump-failed",
            "resume_command": command,
        },
    )

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "remote-pcdump-failed" in " ".join(result["bounded_reasons"])
    assert result["bounded_resume_commands"] == [command]
    assert command in result["next_steps"]


def test_remote_retained_source_blocker_blocks_ceiling():
    node = dict(
        _node_wrong(),
        stop_reason="remote-retained-source-dependency-context-mismatch",
    )

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "remote-retained-source-dependency-context-mismatch" in " ".join(
        result["bounded_reasons"]
    )


def test_bounded_budget_blocks_ceiling():
    node = dict(_node_wrong(), stop_condition={"kind": "budget-exhausted"})

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "budget-exhausted" in " ".join(result["bounded_reasons"])


def test_directed_exhausted_byte_mismatches_classify_as_practical_ceiling():
    result = classify_allocator_ceiling([_directed_exhausted()], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "directed-source-exhausted"
    assert result["directed_source_exhausted"] is True
    assert result["source_shape_exhausted"] is True
    assert result["backend_blockers"] == [
        {
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
            "mutators": [
                "transform-corpus:coloring_register_steering:0",
                "reorder_local_decls",
            ],
        }
    ]
    assert result["exit_code"] == 3


def test_directed_backend_blockers_keep_register_class_identity():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"] = [
        {
            "class_id": 0,
            "valid": True,
            "applied_mutator": "transform-corpus:gpr",
            "checkdiff_gate": "byte_mismatch",
            "proof_assignments": {
                "satisfied": [],
                "blocked": [
                    {
                        "original_ig": 7,
                        "new_ig": 7,
                        "desired_phys": 2,
                        "assigned_phys": 3,
                    }
                ],
                "abstained": [],
            },
        },
        {
            "class_id": 1,
            "valid": True,
            "applied_mutator": "transform-corpus:fpr",
            "checkdiff_gate": "byte_mismatch",
            "proof_assignments": {
                "satisfied": [],
                "blocked": [
                    {
                        "original_ig": 7,
                        "new_ig": 7,
                        "desired_phys": 2,
                        "assigned_phys": 3,
                    }
                ],
                "abstained": [],
            },
        },
    ]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["backend_blockers"] == [
        {
            "class_id": 0,
            "original_ig": 7,
            "new_ig": 7,
            "desired_phys": 2,
            "assigned_phys": 3,
            "mutators": ["transform-corpus:gpr"],
        },
        {
            "class_id": 1,
            "original_ig": 7,
            "new_ig": 7,
            "desired_phys": 2,
            "assigned_phys": 3,
            "mutators": ["transform-corpus:fpr"],
        },
    ]


def test_directed_byte_match_is_actionable():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"][0]["checkdiff_gate"] = "byte_match"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "actionable"
    assert "directed byte_match" in result["positive_proofs"]
    assert result["directed_source_exhausted"] is False
    assert result["backend_blockers"] == []
    assert result["exit_code"] == 0


def test_directed_without_blocked_assignments_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row["proof_assignments"]["blocked"] = []

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert (
        "directed telemetry with blocked proof assignments"
        in result["missing_evidence"]
    )


def test_directed_without_source_transform_rows_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row["applied_mutator"] = "force_phys_assignment"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert (
        "directed telemetry from source-transform candidates"
        in result["missing_evidence"]
    )


def test_directed_unknown_byte_outcome_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row.pop("checkdiff_gate")

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed byte-mismatch outcomes" in result["missing_evidence"]


def test_directed_without_source_shape_drained_signal_is_incomplete():
    evidence = _directed_exhausted()
    evidence["accounting"].pop("source_shape_drained")

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed source-shape drained signal" in result["missing_evidence"]


def test_directed_gate_progress_is_actionable_not_ceiling():
    evidence = _directed_exhausted()
    evidence["gate"]["passed"] = True
    evidence["gate"]["reason"] = "attributable_progress"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "actionable"
    assert "directed attributable_progress" in result["positive_proofs"]
    assert result["directed_source_exhausted"] is False
    assert result["backend_blockers"] == []


def test_directed_budget_exhaustion_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["budget_exhausted"] = True

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search budget exhausted" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_directed_producer_failure_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["producer_failed"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search producer failed" in result["bounded_reasons"]


def test_directed_score_failure_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["score_failed"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search score failed" in result["bounded_reasons"]


def test_directed_invalid_telemetry_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["directed_invalid"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search invalid directed telemetry" in result["bounded_reasons"]


def test_directed_invalid_telemetry_row_is_bounded_without_accounting_counter():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"].append(
        {
            "valid": False,
            "invalid_reason": "pcdump_missing",
            "applied_mutator": "transform-corpus:coloring_register_steering:bad",
        }
    )

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search invalid directed telemetry" in result["bounded_reasons"]


def test_directed_compile_failures_with_scored_rows_do_not_bound():
    evidence = _directed_exhausted()
    evidence["accounting"]["compile_failed"] = 2

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert "directed search compile failed" not in result["bounded_reasons"]


def test_directed_candidate_limit_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["stop_reason"] = "candidate-limit"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search candidate-limit" in result["bounded_reasons"]


@pytest.mark.parametrize("union_status", ["inconclusive", "timeout", "failed"])
def test_force_vector_non_match_statuses_are_incomplete(union_status):
    force = _force_match()
    force["force_vector_verify"]["union"]["status"] = union_status

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["union_status"] == union_status
    assert "force-phys verification with union status match" in (
        result["missing_evidence"]
    )


def test_function_mismatch_rejected_in_summary_payload():
    transform = _transform_negative()
    transform["validation_summary"]["function"] = "other_fn"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_solve_delta(), _force_match(), _node_wrong(), transform],
            function="fn_test",
        )


def test_function_mismatch_rejected_in_validation_row():
    validation = {
        "function": "fn_test",
        "validation": [
            {
                "function": "other_fn",
                "outcome": "retained-source-improvement",
            }
        ],
    }

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([validation], function="fn_test")


def test_function_mismatch_rejected_in_validator_payload():
    validation = {
        "function": "fn_test",
        "validation": [
            {
                "outcome": "retained-source-improvement",
                "validator_payload": {"function": "other_fn"},
            }
        ],
    }

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([validation], function="fn_test")


def test_function_mismatch_rejected_in_directed_telemetry_row():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"][0]["function"] = "other_fn"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([evidence], function="fn_test")


def test_flatten_rejects_invalid_scalar_evidence():
    with pytest.raises(EvidenceFormatError):
        flatten_evidence_items([123])


def test_flatten_rejects_invalid_scalar_inside_list():
    with pytest.raises(EvidenceFormatError):
        flatten_evidence_items([[{"function": "fn_test"}, "bad"]])


def test_residual_case_c_source_repair_exhaustion_is_practical_ceiling():
    result = classify_allocator_ceiling(
        [_select_order_residual_case_c(), _residual_simplify_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "residual-case-c-source-repair-exhausted"
    assert result["source_shape_exhausted"] is True
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "terminal-current-source-shape-ceiling"
    assert residual["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    assert residual["simplify_order_exhaustion"]["retained_probe_count"] == 2
    assert residual["simplify_order_exhaustion"]["compiled"] == 72
    assert residual["materialized_actions"] == [
        {
            "target_ig": 44,
            "source_kind": "implicit-temp",
            "source_expression": "add r44,r52,r64",
            "probe_labels": ["window-order-ranked-indexed-byte-ig44-before-0"],
        }
    ]
    assert residual["blocked_source_spans"] == [
        {
            "target_ig": 34,
            "desired_phys": 27,
            "order_move": ["after", 32],
            "order_moves": [["after", 32]],
            "terminal_blocker": "implicit-temp-no-safe-source-move",
            "source": {
                "kind": "copy/coalesce-product",
                "expression": "mr r34,r37",
                "source_file": "candidate.c",
                "source_line": None,
                "confidence": "pcode-first-def",
                "first_def": {
                    "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                    "block_idx": 13,
                    "instr_idx": 0,
                    "opcode": "mr",
                    "operands": "r34,r37",
                },
                "base_virtual": 37,
            },
        }
    ]


def test_residual_case_c_accepts_plan_transform_simplify_exhaustion():
    result = classify_allocator_ceiling(
        [
            _select_order_residual_case_c(),
            _plan_transform_simplify_summary(),
        ],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    residual = result["residual_case_c_source_repair"]
    assert residual["missing_evidence"] == []
    simplify = residual["simplify_order_exhaustion"]
    assert simplify["kind"] == "retained-source-case-c-simplify-order-continuation"
    assert simplify["terminal_blocker"] == (
        "bounded-remote-scored-exhaustion-no-simplify-order-movement"
    )
    assert simplify["source_file"] == "/tmp/work/build/probes/type-width-0.c"
    assert simplify["evaluated_probe_count"] == 6


def test_residual_case_c_normalizes_lower_drift_plan_transform_exhaustion():
    result = classify_allocator_ceiling(
        [
            _select_order_residual_case_c(),
            _plan_transform_simplify_summary(
                kind="retained-source-case-c-lower-drift-residual",
                terminal_blocker=(
                    "bounded-remote-scored-exhaustion-no-ig34-residual-repair"
                ),
            ),
        ],
        function="fn_test",
    )

    residual = result["residual_case_c_source_repair"]
    simplify = residual["simplify_order_exhaustion"]
    assert result["status"] == "practical-ceiling"
    assert simplify["kind"] == "retained-source-case-c-lower-drift-residual"
    assert simplify["terminal_blocker"] == (
        "bounded-remote-scored-exhaustion-no-ig34-residual-repair"
    )
    assert simplify["residual_hit_count"] == 0
    assert simplify["lost_lower_drift_count"] == 2
    assert simplify["first_divergence_moved_count"] == 0


def test_residual_case_c_accepts_post_source_owner_exhaustion():
    result = classify_allocator_ceiling(
        [_post_source_owner_backtrack_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "residual-case-c-source-repair-exhausted"
    assert result["source_shape_exhausted"] is True
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "terminal-current-source-shape-ceiling"
    assert residual["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    assert residual["missing_evidence"] == []
    post_owner = residual["post_source_owner_exhaustion"]
    assert post_owner["terminal_blocker"] == "post-source-owner-exhausted"
    assert post_owner["evaluated_probe_count"] == 2
    assert post_owner["attempted_targets"] == {"34": 27}
    assert post_owner["protected_targets"] == {"44": 25}
    assert post_owner["skipped_current_owner_labels"] == [
        "window-order-ranked-indexed-byte-ig34-after-0"
    ]
    assert residual["materialized_actions"] == [
        {
            "target_ig": 34,
            "source_kind": "copy/coalesce-product",
            "source_expression": None,
            "probe_labels": ["window-order-ranked-indexed-byte-ig34-after-1"],
        }
    ]


def test_common_subexpr_coalesce_exhaustion_is_practical_ceiling():
    result = classify_allocator_ceiling(
        [_common_subexpr_coalesce_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "residual-case-c-source-repair-exhausted"
    assert result["source_shape_exhausted"] is True
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "terminal-current-source-shape-ceiling"
    assert residual["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    assert residual["missing_evidence"] == []
    common_subexpr = residual["common_subexpr_coalesce_exhaustion"]
    assert common_subexpr["terminal_blocker"] == (
        "common-subexpr-coalesce-source-probes-exhausted"
    )
    assert common_subexpr["evaluated_probe_count"] == 2
    assert common_subexpr["attempted_targets"] == {"34": 27, "40": 25}
    assert common_subexpr["protected_targets"] == {"44": 25}
    assert residual["materialized_actions"] == [
        {
            "target_igs": [34, 40],
            "source_kind": "common-source-shared-base-temp",
            "source_expression": "u8* common_source_r37_probe = dst;",
            "probe_labels": [
                "retained_gpr_common_subexpr_coalesce_source@0"
            ],
        }
    ]


def test_allocator_ceiling_common_subexpr_residual_hit_plus_simplify_is_actionable():
    simplify = _target_only_simplify_exhausted(force_phys={"34": 27})
    simplify["source_file"] = "/tmp/work/build/probes/common-subexpr@0.c"
    simplify["pcdump"] = "/tmp/work/build/probes/common-subexpr@0.pcdump.txt"
    simplify["protected_force_phys"] = {"44": 25}

    result = classify_allocator_ceiling(
        [_common_subexpr_coalesce_residual_hit(), simplify],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == (
        "retained-frontiers-next-source-actionable-lane"
    )
    assert result["missing_evidence"] == []
    continuation = result["next_frontier"]["continuation"]
    assert continuation["route"] == "retained-common-subexpr-residual-handoff"
    assert continuation["source_retained"] == "/tmp/work/build/probes/common-subexpr@0.c"
    assert continuation["pcdump_path"] == "/tmp/work/build/probes/common-subexpr@0.pcdump.txt"
    assert continuation["target_score"]["matched"] == 1
    assert continuation["preserved_force_phys"] == {"44": 25}
    assert continuation["protected_force_phys"] == {"44": 25}
    assert continuation["residual_force_phys"] == {"34": 27}
    exhaustion = continuation["residual_simplify_exhaustion"]
    assert exhaustion["compiled"] == 77
    assert exhaustion["progress_hits"] == 0


def test_allocator_ceiling_common_subexpr_residual_accepts_unscoped_first_divergence():
    simplify = _target_only_simplify_exhausted(force_phys={"34": 27})
    simplify["source_file"] = "/tmp/work/build/probes/common-subexpr@0.c"
    simplify["pcdump"] = "/tmp/work/build/probes/common-subexpr@0.pcdump.txt"
    simplify["protected_force_phys"] = {"44": 25}

    result = classify_allocator_ceiling(
        [
            _common_subexpr_coalesce_residual_hit(),
            _first_divergence_advisory(),
            simplify,
        ],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == (
        "retained-frontiers-next-source-actionable-lane"
    )
    assert result["missing_evidence"] == []
    assert result["next_frontier"]["continuation"]["route"] == (
        "retained-common-subexpr-residual-handoff"
    )


def test_target_live_range_blocker_chain_exhaustion_is_practical_ceiling():
    result = classify_allocator_ceiling(
        [_target_live_range_blocker_chain_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "residual-case-c-source-repair-exhausted"
    residual = result["residual_case_c_source_repair"]
    assert residual["complete"] is True
    assert residual["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    target_live_range = residual["target_live_range_repair_exhaustion"]
    assert target_live_range["terminal_blocker"] == (
        "blocker-color-chain-source-probes-exhausted"
    )
    assert target_live_range["attempted_targets"] == {"44": 25}
    assert target_live_range["protected_targets"] == {"34": 27}
    assert target_live_range["blocker_color_chains"][0][1]["blocker_ig"] == 41
    assert residual["materialized_actions"] == [
        {
            "target_igs": [44],
            "source_kind": "value-side-duplicate-temp",
            "source_expression": "sorted_names[j]",
            "blocker_color_chain": [
                {
                    "target_ig": 34,
                    "target_phys": 27,
                    "blocker_ig": 44,
                    "blocker_phys": 27,
                },
                {
                    "target_ig": 44,
                    "target_phys": 25,
                    "blocker_ig": 41,
                    "blocker_phys": 25,
                },
            ],
            "probe_labels": [
                "retained_gpr_case_c_target_live_range_repair@0"
            ],
        }
    ]
    assert residual["unsupported_source_owner_spans"] == [
        {
            "kind": "blocker-chain-source-owner",
            "target_ig": 34,
            "target_phys": 27,
            "blocker_ig": 44,
            "blocker_phys": 27,
            "terminal_blocker": "blocker-color-chain-source-probes-exhausted",
            "source_kind": "implicit-temp",
            "source_expression": "add r44,r52,r64",
            "source_file": "build/probes/blocker-chain@0.c",
            "source_line": None,
            "confidence": "pcode-first-def",
            "first_def": {
                "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                "opcode": "add",
                "operands": "r44,r52,r64",
            },
        },
        {
            "kind": "blocker-chain-operand-source-owner",
            "target_ig": 34,
            "target_phys": 27,
            "blocker_ig": 44,
            "blocker_phys": 27,
            "operand_index": 1,
            "operand_virtual": 52,
            "operand_assigned_reg": 24,
            "terminal_blocker": "blocker-color-chain-source-probes-exhausted",
            "source_kind": "local",
            "source_expression": "case_c_max_idx_probe",
            "source_file": "build/probes/blocker-chain@0.c",
            "source_line": 12,
            "confidence": "source-owner",
        },
        {
            "kind": "blocker-chain-operand-source-owner",
            "target_ig": 34,
            "target_phys": 27,
            "blocker_ig": 44,
            "blocker_phys": 27,
            "operand_index": 2,
            "operand_virtual": 64,
            "operand_assigned_reg": 28,
            "terminal_blocker": "blocker-color-chain-source-probes-exhausted",
            "source_kind": "local",
            "source_expression": "sorted_names_totals_idx_probe_2",
            "source_file": "build/probes/blocker-chain@0.c",
            "source_line": 14,
            "confidence": "source-owner",
        },
        {
            "kind": "blocker-chain-source-owner",
            "target_ig": 44,
            "target_phys": 25,
            "blocker_ig": 41,
            "blocker_phys": 25,
            "terminal_blocker": "blocker-color-chain-source-probes-exhausted",
            "source_kind": "implicit-temp",
            "source_expression": "rlwinm r41,r45,0,24,31",
            "source_file": "build/probes/blocker-chain@0.c",
            "source_line": None,
            "confidence": "pcode-first-def",
            "first_def": {
                "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                "opcode": "rlwinm",
                "operands": "r41,r45,0,24,31",
            },
        },
        {
            "kind": "blocker-chain-operand-source-owner",
            "target_ig": 44,
            "target_phys": 25,
            "blocker_ig": 41,
            "blocker_phys": 25,
            "operand_index": 1,
            "operand_virtual": 45,
            "operand_assigned_reg": 26,
            "terminal_blocker": "blocker-color-chain-source-probes-exhausted",
            "source_kind": "local",
            "source_expression": (
                "window_order_mnDiagram_804A076C_sorted_names_index_probe"
            ),
            "source_file": "build/probes/blocker-chain@0.c",
            "source_line": 16,
            "confidence": "source-owner",
        },
        {
            "kind": "exhausted-repair-strategy",
            "probe_id": "retained_gpr_case_c_target_live_range_repair@0",
            "terminal_blocker": "blocker-color-chain-source-probes-exhausted",
            "source_probe_provenance_kind": "target-aware-value-side-temp",
            "strategy": "value-side-duplicate-temp",
            "source_expression": "sorted_names[j]",
            "address_expression": "mnDiagram_804A076C.sorted_names[max_idx]",
            "rewritten_expression": None,
            "exhaustion_key": "value-side-duplicate-temp:sorted_names[j]",
        },
    ]


def test_target_live_range_blocker_chain_requires_scored_evidence():
    for evidence in (
        _target_live_range_blocker_chain_exhausted(
            status="materialized-not-scored",
            evaluated=0,
        ),
        _target_live_range_blocker_chain_exhausted(
            evaluated=2,
            unscoreable=2,
        ),
    ):
        result = classify_allocator_ceiling([evidence], function="fn_test")
        assert result["status"] == "incomplete"
        residual = result["residual_case_c_source_repair"]
        assert residual["complete"] is False
        assert residual["target_live_range_repair_exhaustion"] is None


def test_target_live_range_fpr_interference_exhaustion_is_practical_ceiling():
    result = classify_allocator_ceiling(
        [_target_live_range_fpr_interference_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "residual-case-c-source-repair-exhausted"
    residual = result["residual_case_c_source_repair"]
    assert residual["complete"] is True
    target_live_range = residual["target_live_range_repair_exhaustion"]
    assert target_live_range["terminal_blocker"] == (
        "target-aware-live-range-interference-probes-exhausted"
    )
    assert target_live_range["attempted_targets"] == {"37": 26}
    assert target_live_range["protected_targets"] == {"32": 26}
    assert residual["materialized_actions"] == [
        {
            "target_igs": [37],
            "source_kind": "interferer-expression-temp",
            "source_expression": "row_offset_adj",
            "blocker_color_chain": None,
            "probe_labels": [
                "retained_fpr_case_c_target_live_range_repair@0"
            ],
        },
        {
            "target_igs": [37],
            "source_kind": "scalar-duplicate-temp",
            "source_expression": "row_offset_adj",
            "blocker_color_chain": None,
            "probe_labels": [
                "retained_fpr_case_c_target_live_range_repair@1"
            ],
        },
        {
            "target_igs": [37],
            "source_kind": "scalar-paired-overlap-temp",
            "source_expression": "row_offset_adj",
            "blocker_color_chain": None,
            "probe_labels": [
                "retained_fpr_case_c_target_live_range_repair@2"
            ],
        },
    ]
    assert residual["unsupported_source_owner_spans"] == [
        {
            "kind": "exhausted-repair-strategy",
            "probe_id": "retained_fpr_case_c_target_live_range_repair@0",
            "terminal_blocker": (
                "target-aware-live-range-interference-probes-exhausted"
            ),
            "source_probe_provenance_kind": "target-aware-live-range-anchor",
            "strategy": "interferer-expression-temp",
            "source_expression": "row_offset_adj",
            "address_expression": None,
            "rewritten_expression": None,
            "exhaustion_key": "target-aware-live-range-anchor",
        },
        {
            "kind": "exhausted-repair-strategy",
            "probe_id": "retained_fpr_case_c_target_live_range_repair@1",
            "terminal_blocker": (
                "target-aware-live-range-interference-probes-exhausted"
            ),
            "source_probe_provenance_kind": (
                "target-aware-scalar-interference-shape"
            ),
            "strategy": "scalar-duplicate-temp",
            "source_expression": "row_offset_adj",
            "address_expression": None,
            "rewritten_expression": (
                "target_repair_scalar_duplicate_ig37_probe"
            ),
            "exhaustion_key": "target-aware-scalar-interference-shape",
        },
        {
            "kind": "exhausted-repair-strategy",
            "probe_id": "retained_fpr_case_c_target_live_range_repair@2",
            "terminal_blocker": (
                "target-aware-live-range-interference-probes-exhausted"
            ),
            "source_probe_provenance_kind": "target-aware-scalar-pair-overlap",
            "strategy": "scalar-paired-overlap-temp",
            "source_expression": "row_offset_adj",
            "address_expression": None,
            "rewritten_expression": "target_repair_scalar_pair_ig37_probe",
            "exhaustion_key": "target-aware-scalar-pair-overlap",
        },
    ]


def test_target_live_range_fpr_terminal_spans_name_exhausted_source_owners():
    evidence = _target_live_range_fpr_interference_exhausted()
    summary = evidence["validation_summary"][
        "retained_case_c_target_live_range_repair_summary"
    ]
    summary["source_owner_terminal_spans"] = [
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset_adj",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
            "candidate_count": 10,
            "materialized_count": 3,
            "rejection_reasons": {"source-expression-not-indexed-byte": 7},
        },
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset - 0.4f",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
            "candidate_count": 10,
            "materialized_count": 3,
            "rejection_reasons": {"source-expression-not-indexed-byte": 7},
        },
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 32,
            "interferer_phys": 26,
            "source_expression": "col_offset",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
            "candidate_count": 10,
            "materialized_count": 3,
            "rejection_reasons": {"source-expression-not-indexed-byte": 7},
        },
    ]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    residual = result["residual_case_c_source_repair"]
    assert result["status"] == "incomplete"
    assert residual["complete"] is False
    assert residual["target_live_range_repair_exhaustion"] is None


def test_residual_case_c_accepts_terminal_next_source_owner_proof():
    evidence = _target_live_range_fpr_interference_exhausted()
    summary = evidence["validation_summary"][
        "retained_case_c_target_live_range_repair_summary"
    ]
    summary["source_owner_terminal_spans"] = [
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset_adj",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "terminal-next-source-owner-exhausted",
            "inspected_owner_nodes": [
                {
                    "source_expression": "row_offset",
                    "status": "rejected",
                    "reason": "source-expression-not-found",
                }
            ],
        },
    ]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "practical-ceiling"
    residual = result["residual_case_c_source_repair"]
    assert residual["complete"] is True
    spans = residual["unsupported_source_owner_spans"]
    terminal = [
        span for span in spans
        if span["kind"] == "target-live-range-source-owner-terminal"
    ]
    assert terminal[0]["next_source_owner_status"] == (
        "terminal-next-source-owner-exhausted"
    )
    assert terminal[0]["inspected_owner_nodes"]


def test_residual_case_c_reports_materialized_alternate_owner_as_source_actionable():
    evidence = _target_live_range_fpr_interference_exhausted()
    summary = evidence["validation_summary"][
        "retained_case_c_target_live_range_repair_summary"
    ]
    summary["source_owner_terminal_spans"] = [
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset_adj",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "materialized",
            "alternate_source_owner_probe_labels": [
                "retained_case_c_alternate_source_owner_discovery@0"
            ],
            "inspected_owner_nodes": [
                {"source_expression": "row_offset", "status": "candidate"}
            ],
        },
    ]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["complete"] is False
    assert residual["target_live_range_repair_exhaustion"] is None


def test_target_live_range_fpr_anchor_only_exhaustion_is_incomplete():
    result = classify_allocator_ceiling(
        [_target_live_range_fpr_anchor_only_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["complete"] is False
    assert residual["target_live_range_repair_exhaustion"] is None


def test_residual_case_c_uses_source_bridge_lead_identity_for_plan_summary():
    evidence = _select_order_residual_case_c()
    evidence["terminal_exhaustion_summary"]["best_retained_variants"] = []
    lead = evidence["source_bridge_summary"]["leads"][0]
    lead["source"]["source_file"] = "build/probes/retained@0.c"
    lead["source_probe_diagnostic"]["source_attribution"]["source_file"] = (
        "build/probes/retained@0.c"
    )

    result = classify_allocator_ceiling(
        [
            evidence,
            _plan_transform_simplify_summary(
                source_retained="/tmp/work/build/probes/retained@0.c",
            ),
        ],
        function="fn_test",
    )

    residual = result["residual_case_c_source_repair"]
    assert result["status"] == "practical-ceiling"
    assert "select-order best retained source identity" not in residual[
        "missing_evidence"
    ]
    assert residual["simplify_order_exhaustion"]["source_file"] == (
        "/tmp/work/build/probes/retained@0.c"
    )


def test_residual_case_c_dedupes_duplicate_materialized_actions():
    evidence = _select_order_residual_case_c()
    evidence["source_bridge_summary"]["leads"].append(
        dict(evidence["source_bridge_summary"]["leads"][1])
    )

    result = classify_allocator_ceiling(
        [
            evidence,
            _plan_transform_simplify_summary(),
        ],
        function="fn_test",
    )

    residual = result["residual_case_c_source_repair"]
    assert result["status"] == "practical-ceiling"
    assert residual["materialized_actions"] == [
        {
            "target_ig": 44,
            "source_kind": "implicit-temp",
            "source_expression": "add r44,r52,r64",
            "probe_labels": ["window-order-ranked-indexed-byte-ig44-before-0"],
        }
    ]


def test_residual_case_c_source_repair_waits_for_simplify_exhaustion():
    result = classify_allocator_ceiling(
        [_select_order_residual_case_c()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "incomplete"
    assert residual["missing_evidence"] == [
        "matching retained simplify-order no-improvement exhaustion"
    ]


def test_residual_case_c_source_repair_rejects_unblocked_bridge():
    evidence = _select_order_residual_case_c()
    evidence["source_bridge_summary"]["status"] = "resolved"

    result = classify_allocator_ceiling(
        [evidence, _residual_simplify_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "incomplete"
    assert "blocked implicit-temp/copy-product source span" in residual[
        "missing_evidence"
    ]


def test_residual_case_c_source_repair_requires_matching_simplify_source():
    simplify = _residual_simplify_exhausted()
    simplify["source_file"] = "/tmp/work/build/probes/other.c"

    result = classify_allocator_ceiling(
        [_select_order_residual_case_c(), simplify],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "incomplete"
    assert residual["simplify_order_exhaustion"] is None


def test_residual_case_c_source_repair_requires_retained_residual_evidence():
    simplify = _residual_simplify_exhausted()
    simplify["retained_mode"] = False

    result = classify_allocator_ceiling(
        [_select_order_residual_case_c(), simplify],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "incomplete"
    assert residual["simplify_order_exhaustion"] is None


def test_residual_case_c_source_repair_rejects_local_source_kind():
    evidence = _select_order_residual_case_c()
    lead = evidence["source_bridge_summary"]["leads"][0]
    lead["source"]["kind"] = "local"
    lead["source_probe_diagnostic"]["source_attribution"]["kind"] = "local"

    result = classify_allocator_ceiling(
        [evidence, _residual_simplify_exhausted()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    residual = result["residual_case_c_source_repair"]
    assert residual["status"] == "incomplete"
    assert residual["blocked_source_spans"] == []


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_allocator_ceiling_cli_json_practical_ceiling(tmp_path):
    evidence_path = _write_json(
        tmp_path / "evidence.json",
        [_solve_delta(), _force_match(), _node_wrong(), _transform_negative()],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["terminal_reason"] == "target-only-allocator-rotation"


def test_allocator_ceiling_cli_text_lists_next_steps(tmp_path):
    evidence_path = _write_json(tmp_path / "evidence.json", [_solve_delta()])
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: incomplete" in result.output
    assert "force-phys verification with union status match" in result.output


def test_allocator_ceiling_cli_text_lists_target_only_backprojection(tmp_path):
    force = _force_match()
    force["force_vector"] = "class0:ig40:phys=r25"
    delta = _bare_delta()
    delta["missing_virtuals"][0]["source"] = {
        "kind": "local",
        "expression": "target_value",
    }
    evidence_path = _write_json(
        tmp_path / "evidence.json",
        [
            delta,
            force,
            _node_wrong(),
            _transform_negative(),
            _target_only_backprojection_input(tmp_path),
        ],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 0
    assert "target-only backprojection:" in result.output
    assert "- first divergence: class=0 ig40" in result.output
    assert "target-only source levers:" in result.output
    assert "local target_value" in result.output


def test_allocator_ceiling_cli_text_lists_backend_blockers(tmp_path):
    evidence_path = _write_json(tmp_path / "directed.json", _directed_exhausted())
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: practical-ceiling" in result.output
    assert "backend blockers:" in result.output
    assert "ig32->ig32 wants 28 got 26" in result.output


def test_allocator_ceiling_cli_json_accepts_expression_interferer_terminal(tmp_path):
    evidence_path = _write_json(
        tmp_path / "expression.json",
        _expression_interferer_terminal("fn_test"),
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 3
    assert result.output
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["terminal_reason"] == "expression-scored-fpr-allocator-ceiling"
    assert payload["expression_interferer_terminal"]["evidence"]["focus_ig"] == 32


def test_allocator_ceiling_cli_json_accepts_full_retained_frontiers_aggregate(
    tmp_path,
):
    evidence_path = _write_json(
        tmp_path / "retained.json",
        _retained_frontiers_aggregate(),
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    assert payload["missing_evidence"] == []


def test_allocator_ceiling_cli_text_lists_retained_frontiers_meta_ceiling(
    tmp_path,
):
    evidence_path = _write_json(
        tmp_path / "retained.json",
        _retained_frontiers_aggregate(),
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "retained-frontiers meta-ceiling:" in result.output
    assert "post-ceiling-source-model-proof" in result.output
    assert "ig34 wants r27 got r24" in result.output


def test_allocator_ceiling_text_lists_expression_interferer_terminal(tmp_path):
    evidence_path = _write_json(
        tmp_path / "expression.json",
        _expression_interferer_terminal("fn_test"),
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: practical-ceiling" in result.output
    assert "expression terminal:" in result.output
    assert "col_offset ig32 wants f28 got f26" in result.output
    assert "row_offset ig37 wants f26 got f28" in result.output


def test_allocator_ceiling_cli_rejects_mixed_function(tmp_path):
    evidence_path = _write_json(tmp_path / "evidence.json", [_solve_delta("other_fn")])
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 2
    assert "not fn_test" in result.output


def test_allocator_ceiling_cli_rejects_unscoped_evidence(tmp_path):
    evidence_path = _write_json(
        tmp_path / "evidence.json",
        [{"status": "exhausted", "wrong_register_exhausted": True}],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 2
    assert "has no function scope" in result.output


def test_allocator_ceiling_cli_accepts_multiple_evidence_files(tmp_path):
    solve_path = _write_json(tmp_path / "solve.json", _bare_delta())
    rest_path = _write_json(
        tmp_path / "rest.json",
        [_force_match(), _node_wrong(), _transform_negative()],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(solve_path),
        "--evidence", str(rest_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["evidence_count"] == 4


def test_allocator_ceiling_cli_lists_residual_case_c_source_blockers(tmp_path):
    select_order_path = _write_json(
        tmp_path / "select_order.json",
        _select_order_residual_case_c(),
    )
    simplify_path = _write_json(
        tmp_path / "simplify.json",
        _residual_simplify_exhausted(),
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(select_order_path),
        "--evidence", str(simplify_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: practical-ceiling" in result.output
    assert "residual-case-c-source-repair-exhausted" in result.output
    assert "residual Case-C source blockers:" in result.output
    assert "ig34 copy/coalesce-product mr r34,r37" in result.output
    assert "retained simplify-order exhausted: 2 retained, 72 compiled" in result.output


def test_allocator_ceiling_cli_lists_unsupported_source_owner_spans(tmp_path):
    evidence_path = _write_json(
        tmp_path / "target_live_range.json",
        _target_live_range_blocker_chain_exhausted(),
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "unsupported source-owner spans:" in result.output
    assert (
        "ig44 implicit-temp add r44,r52,r64 blocks ig34->r27 on r27"
        in result.output
    )
    assert (
        "ig41 implicit-temp rlwinm r41,r45,0,24,31 blocks ig44->r25 on r25"
        in result.output
    )
    assert (
        "retained_gpr_case_c_target_live_range_repair@0 "
        "value-side-duplicate-temp value=sorted_names[j]"
    ) in result.output


def test_allocator_ceiling_cli_lists_pcode_operand_terminal_spans(tmp_path):
    evidence = _target_live_range_blocker_chain_exhausted()
    summary = evidence["validation_summary"][
        "retained_case_c_target_live_range_repair_summary"
    ]
    summary["source_owner_terminal_spans"] = [
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_gpr_case_c_target_live_range_repair",
            "target_ig": 44,
            "target_phys": 25,
            "interferer_ig": 52,
            "source_expression": "mr r52,r54",
            "source_type": "int",
            "source_owner_kind": "copy/coalesce-product",
            "source_owner_base_virtual": 54,
            "source_owner_first_def": {
                "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                "opcode": "mr",
                "operands": "r52,r54",
            },
            "operand_index": 1,
            "operand_virtual": 52,
            "status": "blocked",
            "terminal_blocker": "target-aware-repair-source-span-not-found",
            "candidate_count": 10,
            "materialized_count": 0,
            "rejection_reasons": {
                "unsafe-source-expression": 1,
                "source-expression-not-indexed-byte": 7,
            },
        },
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_gpr_case_c_target_live_range_repair",
            "target_ig": 44,
            "target_phys": 25,
            "interferer_ig": 64,
            "source_expression": "lwz r64,max_idx(r1)",
            "source_type": "int",
            "source_owner_kind": "load/store-address",
            "source_owner_first_def": {
                "pass_name": "BEFORE GLOBAL OPTIMIZATION",
                "opcode": "lwz",
                "operands": "r64,max_idx(r1)",
            },
            "stack_symbol": "max_idx",
            "operand_index": 2,
            "operand_virtual": 64,
            "operand_live_range": [38, 41],
            "status": "blocked",
            "terminal_blocker": "target-aware-repair-source-span-not-found",
            "candidate_count": 10,
            "materialized_count": 0,
            "rejection_reasons": {
                "unsafe-source-expression": 1,
                "source-expression-not-indexed-byte": 7,
            },
        },
    ]
    evidence_path = _write_json(tmp_path / "target_live_range.json", evidence)
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert (
        "ig44 copy/coalesce-product mr r52,r54 -> "
        "target-aware-repair-source-span-not-found base r54"
    ) in result.output
    assert (
        "ig44 load/store-address lwz r64,max_idx(r1) -> "
        "target-aware-repair-source-span-not-found stack max_idx"
    ) in result.output

    payload = classify_allocator_ceiling([evidence], function="fn_test")
    spans = payload["residual_case_c_source_repair"][
        "unsupported_source_owner_spans"
    ]
    terminal_spans = [
        span for span in spans
        if span["kind"] == "target-live-range-source-owner-terminal"
    ]
    assert {
        (span["source_owner_kind"], span["source_expression"])
        for span in terminal_spans
    } == {
        ("copy/coalesce-product", "mr r52,r54"),
        ("load/store-address", "lwz r64,max_idx(r1)"),
    }
    assert terminal_spans[0]["source_owner_base_virtual"] == 54
    assert terminal_spans[1]["operand_live_range"] == [38, 41]


@pytest.mark.parametrize("payload", [123, [{"function": "fn_test"}, "bad"]])
def test_allocator_ceiling_cli_rejects_invalid_evidence_shape(tmp_path, payload):
    evidence_path = _write_json(tmp_path / "bad.json", payload)
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 2
    assert "evidence must be a JSON object" in result.output


def test_allocator_ceiling_cli_rejects_missing_file(tmp_path):
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(tmp_path / "missing.json"),
    ])

    assert result.exit_code == 2
    assert "could not read --evidence" in result.output


def _inline_local_write_terminal_payload(function="mnDiagram_DrawCellNumber"):
    score_row = {
        "candidate_id": "local-write-0001",
        "family": "inline-local-write-helper",
        "strategy": "block-macro",
        "source_model_layer_dimension_id": "inline-local-write-helper",
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
        "expression_score": {"matched": 0, "targeted": 3, "virtual_distance": 3},
        "structural_guard": {"accepted": True},
        "target_matched": 0,
        "target_targeted": 3,
        "expression_matched": 0,
        "expression_targeted": 3,
        "terminal_safe": True,
    }
    terminal_reason = (
        "inline-local-write-helper-family-exhausted/"
        "no-target-or-expression-improvement"
    )
    synthesis = {
        "status": "synthesis-exhausted",
        "evidence_status": "artifact-score-rows",
        "attempted_equivalence_classes": ["inline-local-write-helper"],
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
            "attempted_equivalence_classes": ["inline-local-write-helper"],
            "exhausted_dimensions": synthesis["exhausted_dimensions"],
            "source_family_synthesis": synthesis,
        },
    }


def test_allocator_ceiling_consumes_inline_local_write_terminal_meta(tmp_path):
    artifact = _write_json(
        tmp_path / "suggest_inlines_local_write_terminal.json",
        _inline_local_write_terminal_payload(),
    )
    retained = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=["mnDiagram_DrawCellNumber"],
        artifacts=[artifact],
    )

    result = classify_allocator_ceiling(
        [retained],
        function="mnDiagram_DrawCellNumber",
    )

    assert result["status"] == "practical-ceiling"
    assert result["source_shape_exhausted"] is True
    retained_meta = result["retained_frontiers_meta_ceiling"]
    assert retained_meta["status"] == "terminal-current-source-shape-ceiling"
    proof = retained_meta["terminal_proof"]
    assert proof["candidate_scores"][0]["source_retained"] == (
        "build/diagnostics/local-write-0001.c"
    )
