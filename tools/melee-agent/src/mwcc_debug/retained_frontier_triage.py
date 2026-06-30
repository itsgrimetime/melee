"""Rank retained-frontier diagnostics after allocator-ceiling analysis.

This module is intentionally read-only. It walks existing JSON artifacts,
normalizes the retained-frontier shapes emitted by several diagnostics, applies
terminal closure evidence, and returns the next actionable route when one
remains.
"""

from __future__ import annotations

import glob
import json
import math
import shlex
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .post_source_context_discovery import (
    DISCOVERY_FAMILY as POST_SOURCE_CONTEXT_DISCOVERY_FAMILY,
)
from .post_source_context_discovery import (
    DISCOVERY_KIND as POST_SOURCE_CONTEXT_DISCOVERY_KIND,
)
from .post_source_context_discovery import (
    DRAW_POST_SOURCE_CONTEXT_DIMENSION,
    DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY,
    DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_MODEL,
)


class RetainedFrontierTriageError(ValueError):
    """Raised for invalid retained-frontier triage inputs."""


_ADDI_RESOLVER_KIND = "target-only-backprojection-addi-copy-product-source-resolver"
_ADDI_FAMILY = "target-only-backprojection-addi-copy-product"
_C2_FAMILY = "target-only-c2-sticky-pool"
_COPY_SURVIVED_FAMILY = "copy-survived-pointer-reset"
_COPY_SURVIVED_NODE_SET_TERMINAL_FAMILY = "copy-survived-node-set-exhaustion"
_COPY_SURVIVED_NODE_SET_TERMINAL_KIND = "copy-survived-node-set-exhaustion"
_COPY_SURVIVED_NODE_SET_ROUTE_TERMINAL_REASON = (
    "copy-survived-node-set-route-exhausted/all-wrong-register"
)
_COPY_SURVIVED_NODE_SET_NO_TARGET_PROGRESS_REASON = (
    "copy-survived-node-set-route-exhausted/no-target-progress"
)
_COPY_SURVIVED_NODE_SET_ROUTES_TERMINAL_REASON = (
    "copy-survived-node-set-routes-exhausted/current-source-shape-ceiling"
)
_POST_CEILING_BASELINE_ESCAPE_KINDS = {
    "no-post-ceiling-draw-source-family",
    "no-post-ceiling-sort-source-family",
}
_POST_CEILING_BASELINE_ESCAPE_KIND = "no-post-ceiling-draw-source-family"
_POST_CEILING_BASELINE_ESCAPE_REASON = (
    "no-post-ceiling-draw-source-family/current-source-shape-ceiling"
)
_POST_CEILING_BASELINE_ESCAPE_REASONS = {
    _POST_CEILING_BASELINE_ESCAPE_REASON,
    "no-post-ceiling-sort-source-family/current-source-shape-ceiling",
}
_POST_CEILING_BASELINE_ESCAPE_FAMILY = "post-ceiling-baseline-escape"
_POST_CEILING_CONTINUATION_FAMILY = "post-ceiling-baseline-escape-continuation"
_POST_CEILING_CONTINUATION_KIND = "post-ceiling-baseline-escape-continuation"
_POST_CEILING_CONTINUATION_TERMINAL_KIND = "post-ceiling-continuation-exhausted"
_POST_CEILING_CONTINUATION_TERMINAL_REASON = (
    "post-ceiling-continuation-exhausted/all-candidate-routes-unsupported"
)
_POST_CEILING_CONTINUATION_ROUTE_TERMINAL_REASON = (
    "post-ceiling-continuation-routes-exhausted/current-source-shape-ceiling"
)
_POST_CEILING_SOURCE_MODEL_PROOF_FAMILY = "post-ceiling-source-model-proof"
_INLINE_LEVERAGE_BOUNDARY_FAMILY = "inline-leverage-helper-boundary-continuation"
_INLINE_LEVERAGE_BOUNDARY_KIND = "inline-leverage-helper-boundary-continuation"
_INLINE_LEVERAGE_BOUNDARY_TERMINAL_KIND = (
    "inline-leverage-helper-boundary-exhausted"
)
_INLINE_LEVERAGE_BOUNDARY_TERMINAL_REASON = (
    "inline-leverage-helper-boundary-exhausted/no-ig34-ig44-progress"
)
_POST_CEILING_GPR_SOURCE_MODEL_PROOF_KIND = (
    "post-ceiling-gpr-case-c-source-model-proof"
)
_POST_CEILING_GPR_SOURCE_MODEL_PROOF_REASON = (
    "post-ceiling-gpr-case-c-source-model-ceiling"
)
_POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_KIND = (
    "post-ceiling-gpr-case-c-source-model-synthesis-proof"
)
_POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_REASON = (
    "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
)
_POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_PROOF_KIND = (
    "post-ceiling-fpr-expression-source-model-proof"
)
_POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_PROOF_REASON = (
    "post-ceiling-fpr-expression-source-model-ceiling"
)
_POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_SYNTHESIS_PROOF_KIND = (
    "post-ceiling-fpr-expression-source-model-synthesis-proof"
)
_POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_SYNTHESIS_PROOF_REASON = (
    "post-ceiling-fpr-expression-source-model-synthesis-exhausted"
)
_SELECT_ORDER_TERMINAL_KINDS = {
    "degree-zero-fpr-case-c-source-exhaustion",
    "select-order-source-exhaustion",
}

_SORT_FUNCTION = "mnDiagram_SortNamesByKOs"
_DRAW_FUNCTION = "mnDiagram_DrawCellNumber"
_SORT_SWAP_SLOT_LVALUE_DIMENSION = "sort-swap-slot-lvalue"
_SORT_FULL_SELECTION_SWAP_DIMENSION = "sort-full-selection-swap-source-structure"
_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION = (
    "sort-whole-function-control-data-flow-rewrite"
)
_SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION = (
    "sort-helper-extraction-data-layout-or-cross-function-rewrite"
)
_SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION = (
    "sort-tu-data-symbol-helper-boundary-source-context"
)
_SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION = (
    "sort-unbounded-tu-data-ownership-source-context"
)
_SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION = (
    "sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context"
)
_SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION = (
    "sort-post-cross-tu-selection-swap-source-hypothesis"
)
_SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION = (
    "sort-post-cross-tu-broader-natural-c-rewrite"
)
_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION = (
    "sort-post-broader-natural-inline-boundary-source-hypothesis"
)
_SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION = (
    "sort-post-inline-boundary-selection-emission-source-shape"
)
_SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-inline-boundary-"
    "selection-emission-source-shape"
)
_SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL = (
    "Sort post-inline-boundary selection/emission source-shape synthesis "
    "exhausted bounded selected-name carry, selected total/text lifetime, and "
    "selected-name emission-owner probes seeded from the retained "
    "post-broader inline-boundary one-hit row without jointly preserving "
    "IG34/IG44 under the structural guard. No further modeled "
    "source-actionable Sort family remains after this post-inline-boundary "
    "selection/emission layer."
)
_SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION = (
    "sort-protected-loss-init-lifetime"
)
_SORT_SOURCE_FAMILY_DIMENSIONS = (
    "sort-init-indexed-write",
    "sort-indexed-byte-cache",
    "sort-call-return-copy-local",
    "sort-swap-slot-lvalue",
    _SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION,
    _SORT_FULL_SELECTION_SWAP_DIMENSION,
    _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION,
    _SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION,
    _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION,
    _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION,
    _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
    _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION,
    _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION,
    _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION,
    _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION,
)
_SORT_FALLBACK_DEFERRED_SOURCE_FAMILY_DIMENSIONS = {
    _SORT_FULL_SELECTION_SWAP_DIMENSION,
    _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION,
    _SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION,
    _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION,
    _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION,
    _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
    _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION,
    _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION,
    _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION,
    _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION,
}
_SORT_POST_LOWER_DRIFT_UNSUPPORTED_SOURCE_MODEL = (
    "Sort protected-loss init-lifetime scoring exhausted the bounded lower-drift "
    "source family without jointly preserving IG34/IG44. The next unsupported "
    "source model is the full Sort selection/swap source structure outside the "
    "current protected-loss and init-lifetime families."
)
_SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL = (
    "Sort full selection/swap source-model synthesis exhausted bounded full "
    "selection-loop, comparison-state, selected-name, and swap-emission source "
    "shapes without jointly preserving IG34/IG44. The next unsupported source "
    "span/family is an unmodeled whole-function Sort control/data-flow rewrite "
    "outside the bounded full-selection/swap region replacements."
)
_SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY = (
    "sort-whole-function-control-data-flow-rewrite"
)
_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL = (
    "Sort whole-function control/data-flow source-model synthesis exhausted "
    "bounded function-body rewrites spanning initialization, source-owner flow, "
    "selection state, selected-name/total state, and swap/emission without "
    "jointly recovering IG34/IG44. The next unsupported source span/family is "
    "helper extraction, data layout, or cross-function source-context rewrite "
    "outside the bounded mnDiagram_8023FC28 function-body model."
)
_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY = (
    "sort-helper-extraction-data-layout-or-cross-function-rewrite"
)
_SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL = (
    "Sort helper-extraction, data-layout, and cross-function source-context "
    "synthesis exhausted bounded static inline helper, sorted_names accessor, "
    "and local overlay/accessor source shapes without jointly recovering "
    "IG34/IG44. The next unsupported source span/family is an unmodeled TU-level "
    "data-symbol, helper-boundary, or cross-function source-context rewrite "
    "outside the bounded Sort helper/data-layout model."
)
_SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY = (
    "sort-tu-data-symbol-helper-boundary-source-context"
)
_SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL = (
    "Sort TU-level data-symbol/helper-boundary/cross-function source-context "
    "synthesis exhausted bounded storage-overlay, shared accessor, and "
    "helper-boundary source shapes without jointly recovering IG34/IG44. The "
    "next unsupported source span/family is an unmodeled whole-TU data "
    "declaration or nonlocal source-ownership rewrite outside the bounded Sort "
    "TU source-context model."
)
_SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY = (
    "sort-unbounded-tu-data-ownership-source-context"
)
_SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_MODEL = (
    "Sort unbounded TU data-ownership source-context synthesis exhausted "
    "retained full-TU data declaration, ownership overlay, and nonlocal "
    "accessor rewrites without jointly recovering IG34/IG44. The next "
    "unsupported source span/family is an unmodeled cross-TU symbol/linkage "
    "or compiler data-section ownership model outside retained full-TU "
    "source-context synthesis."
)
_SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY = (
    "sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context"
)
_SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL = (
    "Sort cross-TU symbol/linkage and compiler data-section ownership "
    "source-context synthesis exhausted bounded cross-TU source-context rows "
    "and complementary one-hit recombine evidence without jointly recovering "
    "IG34/IG44. No further modeled source-actionable Sort family remains after "
    "the cross-TU linkage layer."
)
_SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-cross-tu-linkage"
)
_SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER = (
    "no-modeled-source-actionable-family-after-cross-tu-linkage"
)
_SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_MODEL = (
    "Sort post-cross-TU selection/swap source hypothesis layer exhausted "
    "bounded combined source-region probes after the cross-TU layer without "
    "jointly preserving IG34/IG44. No further modeled source-actionable Sort "
    "family remains after this post-cross-TU selection/swap source hypothesis "
    "layer."
)
_SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-selection-swap-source-hypothesis"
)
_SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_TERMINAL_REASON = (
    "sort-post-cross-tu-selection-swap-source-hypothesis-exhausted/"
    "protected-targets-not-jointly-preserved"
)
_SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_MODEL = (
    "Sort post-cross-TU broader natural C rewrite synthesis exhausted "
    "bounded full-unit sort-region rewrites seeded from the retained IG44 "
    "one-hit post-cross-TU selection/swap probe without jointly preserving "
    "IG34/IG44 under the structural guard. No further modeled "
    "source-actionable Sort family remains after this broader natural C "
    "rewrite layer."
)
_SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite"
)
_SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_TERMINAL_REASON = (
    "sort-post-cross-tu-broader-natural-c-rewrite-exhausted/"
    "protected-targets-not-jointly-preserved"
)
_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_MODEL = (
    "Sort post-broader-natural inline-boundary source-hypothesis synthesis "
    "exhausted bounded comparison decision/helper-boundary probes seeded from "
    "the lower-drift broader-natural row without jointly preserving IG34/IG44 "
    "under the structural guard. No further modeled source-actionable Sort "
    "family remains after this post-broader-natural inline-boundary layer."
)
_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis"
)
_SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_REASON = (
    "sort-post-broader-natural-inline-boundary-source-hypothesis-exhausted/"
    "protected-targets-not-jointly-preserved"
)
_SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON = (
    "sort-post-inline-boundary-selection-emission-source-shape-exhausted/"
    "protected-targets-not-jointly-preserved"
)
_SORT_FULL_SELECTION_SWAP_NOT_MATERIALIZED_BLOCKER = (
    "sort-full-selection-swap-source-model-not-materialized"
)
_SORT_SEMANTIC_RECOMBINE_DIMENSION = "sort-semantic-dual-target-recombine"
_SORT_DIRECT_SCORE_SOURCE_FAMILY = "post-meta-sort-direct-score-source"
_SORT_SEMANTIC_RECOMBINE_NEEDS_REAL_SCORE_REASON = (
    "sort-semantic-dual-target-recombine-needs-real-score"
)
_POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY = (
    "post-ceiling-source-model-proof-semantic-recombine"
)
_POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_KIND = (
    "post-ceiling-source-model-semantic-recombine-source-hunks"
)
_SORT_INLINE_BOUNDARY_TARGETS = {"34": 27, "44": 25}
_SORT_PROTECTED_STRUCTURAL_TARGETS = {"34": 27, "44": 25}
_DRAW_SOURCE_FAMILY_DIMENSIONS = (
    "draw-col-cast-product-local",
    "draw-row-translation-scale-split",
    "draw-digit-callarg-fsubs-temp",
    "draw-loop-body-callsite-and-object-base-lifetime-source-context",
    DRAW_POST_SOURCE_CONTEXT_DIMENSION,
)
_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE = (
    "draw-protected-expression-subhunk-reconcile"
)
_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_CLASS_ID = (
    "protected-expression-structural-reconciliation"
)
_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON = (
    "draw-protected-expression-subhunk-reconcile-exhausted/"
    "protected-expression-not-retained"
)
_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-"
    "protected-expression-subhunk-reconcile"
)
_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL = (
    "Draw protected-expression subhunk reconciliation exhausted all scored "
    "recombines without retaining the protected expression anchors. No further "
    "modeled source-actionable Draw family remains after this reconcile layer."
)
_DRAW_COUPLED_FPR_LIFETIME_DIMENSION = "draw-coupled-fpr-expression-lifetime"
_DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_DIMENSION = (
    "draw-alternate-fpr-expression-structure"
)
_DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_EXHAUSTED_NEXT_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-alternate-fpr-expression-structure"
)
_DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_EXHAUSTED_NEXT_MODEL = (
    "Draw alternate FPR expression-structure synthesis exhausted bounded "
    "coupled col_offset/row_offset/digit-callarg expression graph variants; "
    "no modeled source-actionable Draw family remains."
)
_DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION = (
    "draw-loop-body-callsite-and-object-base-lifetime-source-context"
)
_DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-loop-body-callsite-"
    "and-object-base-lifetime-source-context"
)
_DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw loop-body callsite/object-base lifetime source-context synthesis "
    "exhausted bounded preloop object/base lifetime, loop-body callarg/"
    "translate ordering, and lower-hill retained-baseline backtracking source "
    "shapes without improving the retained target/expression floor. No further "
    "modeled source-actionable Draw family remains after this source-context "
    "layer."
)
_DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-source-context-"
    "whole-function-fpr-source-model"
)
_DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-source-context whole-function FPR source-model synthesis "
    "exhausted bounded preloop object/base/data ownership plus loop digit "
    "object, animation, translate, and add-child ownership probes without "
    "improving the retained target/real-expression floor. No further modeled "
    "source-actionable Draw family remains after this whole-function layer."
)
_DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-all-known-frontiers-source-context-hypothesis"
)
_DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-all-known-frontiers-"
    "source-context-hypothesis"
)
_DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-all-known source-context hypothesis after whole-function FPR "
    "ceiling exhausted bounded recombinations and wider source-context owner "
    "shapes without improving the retained target/real-expression floor."
)
_DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION = (
    "draw-post-all-known-loop-product-translate-expression-graph"
)
_DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-all-known-loop-"
    "product-translate-expression-graph"
)
_DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_MODEL = (
    "Draw post-all-known loop product/translate expression-graph synthesis "
    "exhausted bounded loop-index translate, col/row product owner, row-delta "
    "product, and common translate-X call-shape variants without improving the "
    "retained target/real-expression floor. No further modeled source-actionable "
    "Draw family remains after this product/translate expression-graph layer."
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_MODEL = (
    "Draw post-product/translate stack-clean/no-anchor recovery from an "
    "opcode-clean product/translate seed with stack-frame drift and missing "
    "IG32/IG37/IG46 expression anchors."
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery-"
    "exhausted/no-anchor-recovery"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery/"
    "no-source-actionable-anchor-recovery"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-product-translate-"
    "stack-clean-no-anchor-recovery"
)
_DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL = (
    "Draw post-product/translate stack-clean/no-anchor recovery exhausted "
    "bounded row-delta, digit fsubs, col-product owner-transfer, and "
    "frame-clean owner-prune probes without recovering IG32/IG37/IG46 "
    "expression anchors or eliminating the stack-frame drift while preserving "
    "the normalized opcode shape."
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis"
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL = (
    "Draw post-stack-clean/no-anchor FPR source-shape synthesis from the "
    "stack-clean final proof, testing declaration packing, row/column owner "
    "reuse, digit base lifetime, and frame-neutral owner coalescing against "
    "IG32/IG37/IG46 plus the +8 frame drift."
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-"
    "fpr-source-shape-hypothesis"
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor FPR source-shape synthesis exhausted "
    "bounded declaration-packing, row/column owner reuse, digit base lifetime, "
    "coupled row/column, and frame-neutral coalescing probes without recovering "
    "IG32/IG37/IG46 expression anchors or eliminating the stack-frame drift "
    "under the structural guard."
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis-exhausted/"
    "no-floor-improvement"
)
_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER = (
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis/"
    "no-source-actionable-anchor-or-frame-recovery"
)
_DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context"
)
_DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON = (
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context-exhausted/"
    "no-floor-improvement"
)
_DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER = (
    "draw-post-stack-clean-no-anchor-loop-callsite-source-context/"
    "no-target-or-expression-floor-improvement"
)
_DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-stack-loop-callsite-"
    "source-context"
)
_DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor loop-callsite source-context synthesis "
    "exhausted bounded digit object, animation callarg, translate-X/translate-Y "
    "owner, and add-child parent owner probes from the retained post-stack seed "
    "without recovering IG32/IG37/IG46 expression anchors or eliminating "
    "stack-frame drift under the structural guard."
)
_DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY = (
    "draw-post-stack-loop-callsite-expression-anchor-source-ownership"
)
_DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL = (
    "Draw post-stack loop-callsite source-context exhaustion now needs "
    "expression-anchor source ownership for row/column FPR owners, "
    "col_product_owner split product, y_offset/row_offset row-delta source, "
    "and digit base assignment feeding HSD_JObjReqAnimAll."
)
_DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION = (
    "draw-post-row-offset-owner-expression-lifetime"
)
_DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON = (
    "draw-post-row-offset-owner-expression-lifetime-exhausted/no-lifetime-progress"
)
_DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER = (
    "draw-post-row-offset-owner-expression-lifetime/"
    "no-target-or-expression-floor-improvement"
)
_DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-expression-lifetime"
)
_DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL = (
    "Draw post-row-offset-owner expression lifetime synthesis exhausted "
    "bounded row_offset_adj translate-Y, column product, digit callsite, and "
    "coupled lifetime probes from the retained owner-split floor."
)
_STACK_CLEAN_TERMINAL_SUMMARY_FIELDS = (
    "terminal_reason",
    "terminal_blocker",
    "terminal_blockers",
    "next_unsupported_source_dimension",
    "next_unsupported_source_model",
    "next_unsupported_source_family",
    "next_unsupported_source_spans",
    "stack_clean_no_anchor_evidence",
    "post_stack_clean_no_anchor_evidence",
    "exhausted_source_dimension",
    "suppressed_frontier_dimension",
    "suppressed_candidate_id",
    "exhausted_dimensions",
)
_DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS = (
    "draw-coupled-post-meta-fpr-expression-lifetime"
)
_DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL = (
    "Draw coupled post-meta FPR expression lifetime/materialization across "
    "col_offset product, row_offset fsubs, and digit-animation fsubs/callarg temp."
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY = (
    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_KIND = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_KIND = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON = (
    "all-inline-helper-candidates-rejected"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-exhausted/"
    "no-expression-progress"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-helper-boundary-"
    "expression-lifetime"
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL = (
    "Draw helper-boundary expression-lifetime synthesis exhausted bounded "
    "inline/block-helper source shapes after protected-expression reconcile "
    "without recovering the remaining IG32/IG37/IG46 expression anchors. No "
    "further modeled source-actionable Draw family remains in this lane; the "
    "remaining axis is non-source/codegen or allocator behavior."
)
_DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS = {
    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
}

_SUMMARY_KEYS = {
    "retained_case_c_window_order_continuation_summary",
    "retained_case_c_post_source_owner_backtrack_summary",
    "retained_case_c_target_live_range_repair_summary",
    "retained_gpr_common_subexpr_coalesce_source_summary",
    "retained_case_c_simplify_order_continuation_summary",
    "retained_case_c_sensitivity_summary",
}

_TERMINAL_REASONS = {
    "target-only-backprojection-source-probe-continuation-terminal",
    "target-only-c2-sticky-pool-source-attribution-terminal",
    "residual-case-c-source-repair-exhausted",
    "expression-scored-fpr-allocator-ceiling",
    "addi-copy-product-operands-not-source-visible",
    *_POST_CEILING_BASELINE_ESCAPE_REASONS,
    _POST_CEILING_CONTINUATION_TERMINAL_REASON,
    _INLINE_LEVERAGE_BOUNDARY_TERMINAL_REASON,
}

_TERMINAL_STATUSES = {
    "blocked",
    "scored-negative",
    "terminal-blocked",
    "exhausted",
}

_ACTIONABLE_CLASSIFICATIONS = {
    "residual-hit-protected-lower-drift",
    "lower-drift-frontier",
}

_METRIC_KEYS = (
    "evaluated_probe_count",
    "exact_count",
    "protected_negative_count",
    "lost_protected_count",
    "no_target_progress_count",
    "materialized_probe_count",
    "unscoreable_count",
    "baseline_score",
    "best_score",
    "target_hits",
    "protected_preserved",
    "compiled",
    "skipped",
    "compile_failures",
    "gate_rejected",
    "progress_hits",
    "candidate_count",
    "scored_count",
    "failed_count",
    "best_expression_matched",
    "best_expression_targeted",
    "best_expression_virtual_distance",
    "pointer_reset_probe_count",
    "pointer_reset_failed_count",
)

_DRIFT_KEYS = (
    "normalized_diff_lines",
    "target_score_total",
    "virtual_distance",
    "candidate_final_distance",
    "baseline_final_distance",
)


def discover_retained_frontier_artifacts(
    *,
    repo_root: Path,
    artifacts: Iterable[Path | str] | None = None,
    artifact_globs: Iterable[str] | None = None,
    diagnostics_root: Path | str | None = None,
    max_files: int = 2000,
) -> list[Path]:
    """Resolve retained-frontier JSON artifacts from files, dirs, and globs."""
    repo_root = repo_root.expanduser().resolve()
    resolved: list[Path] = []

    for raw in artifacts or []:
        path = _resolve_path(raw, repo_root=repo_root)
        if path.is_dir():
            resolved.extend(sorted(path.rglob("*.json")))
        elif path.is_file():
            resolved.append(path)
        else:
            raise RetainedFrontierTriageError(f"artifact not found: {raw}")

    for raw_glob in artifact_globs or []:
        pattern = str(raw_glob)
        if not Path(pattern).expanduser().is_absolute():
            pattern = str(repo_root / pattern)
        matches = [
            Path(match).expanduser().resolve()
            for match in glob.glob(pattern, recursive=True)
        ]
        resolved.extend(path for path in sorted(matches) if path.is_file())

    if not resolved:
        root = _resolve_path(
            diagnostics_root or Path("build") / "diagnostics",
            repo_root=repo_root,
        )
        if root.is_dir():
            resolved.extend(sorted(root.rglob("*.json")))
        elif diagnostics_root is not None:
            raise RetainedFrontierTriageError(
                f"diagnostics root not found: {diagnostics_root}"
            )

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in resolved:
        resolved_path = path.expanduser().resolve()
        if resolved_path in seen:
            continue
        seen.add(resolved_path)
        unique.append(resolved_path)

    if len(unique) > max_files:
        raise RetainedFrontierTriageError(
            f"scan matched {len(unique)} JSON files; raise --max-files above "
            f"{max_files} to continue"
        )
    return unique


def triage_retained_frontiers(
    *,
    repo_root: Path,
    functions: Iterable[str] | None = None,
    artifacts: Iterable[Path | str] | None = None,
    artifact_globs: Iterable[str] | None = None,
    diagnostics_root: Path | str | None = None,
    max_files: int = 2000,
) -> dict[str, Any]:
    """Return ranked retained frontiers grouped by function."""
    repo_root = repo_root.expanduser().resolve()
    artifact_inputs = list(artifacts or [])
    artifact_glob_inputs = list(artifact_globs or [])
    artifact_paths = discover_retained_frontier_artifacts(
        repo_root=repo_root,
        artifacts=artifact_inputs,
        artifact_globs=artifact_glob_inputs,
        diagnostics_root=diagnostics_root,
        max_files=max_files,
    )
    strict_json = bool(artifact_inputs) and not artifact_glob_inputs and all(
        _resolve_path(raw, repo_root=repo_root).is_file()
        for raw in artifact_inputs
    )
    requested_functions = [fn for fn in (functions or []) if fn]
    requested_set = set(requested_functions)

    raw_frontiers: list[dict[str, Any]] = []
    raw_simplify_exhaustions: list[dict[str, Any]] = []
    match_percent_by_function: dict[str, float | None] = {}
    skipped_artifacts: list[dict[str, str]] = []
    parsed_artifact_count = 0
    for path in artifact_paths:
        try:
            payload = _load_json(path)
        except RetainedFrontierTriageError as exc:
            if strict_json:
                raise
            skipped_artifacts.append({
                "artifact": str(path),
                "reason": str(exc),
            })
            continue
        parsed_artifact_count += 1
        for frontier in _extract_frontiers(payload, artifact=path):
            function = frontier.get("function")
            if not isinstance(function, str) or not function:
                continue
            if requested_set and function not in requested_set:
                continue
            raw_frontiers.append(frontier)
            match_percent = frontier.get("match_percent")
            if (
                function not in match_percent_by_function
                or match_percent_by_function[function] is None
            ):
                match_percent_by_function[function] = match_percent
        raw_simplify_exhaustions.extend(
            _extract_retained_simplify_exhaustions(payload, artifact=path)
        )

    _apply_retained_simplify_exhaustions(raw_frontiers, raw_simplify_exhaustions)
    merged = _merge_frontiers(raw_frontiers)
    _apply_terminal_suppression(merged)

    if requested_functions:
        function_names = requested_functions
    else:
        function_names = sorted({f["function"] for f in merged})

    function_payloads: list[dict[str, Any]] = []
    any_actionable = False
    any_frontier = False
    for function in function_names:
        function_frontiers = [f for f in merged if f["function"] == function]
        existing_frontier_ids = {
            str(frontier.get("frontier_id")) for frontier in function_frontiers
            if frontier.get("frontier_id")
        }
        function_frontiers.extend(
            _retained_terminal_source_model_semantic_recombine_lanes(
                [frontier for frontier in function_frontiers if frontier.get("terminal")],
                existing_frontier_ids=existing_frontier_ids,
            )
        )
        existing_frontier_ids.update(
            str(frontier.get("frontier_id"))
            for frontier in function_frontiers
            if frontier.get("frontier_id")
        )
        function_frontiers.extend(
            _retained_terminal_stack_clean_no_anchor_lanes(
                [frontier for frontier in function_frontiers if frontier.get("terminal")],
                existing_frontier_ids=existing_frontier_ids,
            )
        )
        existing_frontier_ids.update(
            str(frontier.get("frontier_id"))
            for frontier in function_frontiers
            if frontier.get("frontier_id")
        )
        function_frontiers.extend(
            _retained_terminal_draw_helper_boundary_handoff_lanes(
                [frontier for frontier in function_frontiers if frontier.get("terminal")],
                existing_frontier_ids=existing_frontier_ids,
            )
        )
        if function_frontiers:
            any_frontier = True
        ranked = _rank_frontiers(function_frontiers)
        for index, frontier in enumerate(ranked, start=1):
            frontier["rank"] = index

        unexhausted = [
            _public_frontier(frontier)
            for frontier in ranked
            if not frontier.get("terminal")
        ]
        terminal = [
            _public_frontier(frontier)
            for frontier in ranked
            if frontier.get("terminal")
        ]
        next_frontier = next(
            (
                frontier for frontier in unexhausted
                if frontier.get("actionable") and frontier.get("continuation")
            ),
            None,
        )
        if next_frontier is not None:
            any_actionable = True

        function_payloads.append({
            "function": function,
            "current_match_percent": match_percent_by_function.get(function),
            "frontiers": unexhausted,
            "terminal_frontiers": terminal,
            "next_frontier": next_frontier,
            "summary": {
                "unexhausted_count": len(unexhausted),
                "terminal_count": len(terminal),
                "suppressed_by_terminal_count": sum(
                    1 for frontier in terminal
                    if frontier.get("suppressed_by_terminal")
                ),
            },
        })

    status = (
        "actionable"
        if any_actionable
        else (
            "all-known-frontiers-exhausted"
            if any_frontier
            else "no-frontiers-found"
        )
    )
    next_frontier = next(
        (
            function_payload["next_frontier"]
            for function_payload in function_payloads
            if function_payload.get("next_frontier") is not None
        ),
        None,
    )
    payload = {
        "status": status,
        "artifact_count": len(artifact_paths),
        "parsed_artifact_count": parsed_artifact_count,
        "skipped_artifacts": skipped_artifacts,
        "functions": function_payloads,
        "next_frontier": next_frontier,
    }
    for function_payload in function_payloads:
        meta = synthesize_retained_frontier_meta_ceiling(
            payload,
            function=str(function_payload.get("function") or ""),
        )
        if meta.get("status") != "not-present":
            function_payload["meta_ceiling"] = meta
    metas = [
        function_payload["meta_ceiling"]
        for function_payload in function_payloads
        if isinstance(function_payload.get("meta_ceiling"), Mapping)
    ]
    if metas:
        payload["meta_ceiling"] = metas[0] if len(metas) == 1 else metas
    return payload


def render_retained_frontier_text(payload: Mapping[str, Any]) -> str:
    """Render a compact human-readable retained-frontier triage summary."""
    lines = [f"status: {payload.get('status')}"]
    lines.append(f"artifacts: {payload.get('artifact_count', 0)}")
    if payload.get("skipped_artifacts"):
        lines.append(f"skipped_artifacts: {len(payload['skipped_artifacts'])}")
    for function_payload in payload.get("functions", []) or []:
        if not isinstance(function_payload, Mapping):
            continue
        lines.append("")
        lines.append(f"{function_payload.get('function')}:")
        summary = function_payload.get("summary")
        if isinstance(summary, Mapping):
            lines.append(
                "  "
                f"unexhausted={summary.get('unexhausted_count', 0)} "
                f"terminal={summary.get('terminal_count', 0)} "
                f"suppressed={summary.get('suppressed_by_terminal_count', 0)}"
            )
        next_frontier = function_payload.get("next_frontier")
        if isinstance(next_frontier, Mapping):
            continuation = next_frontier.get("continuation")
            route = (
                continuation.get("route")
                if isinstance(continuation, Mapping)
                else None
            )
            lines.append(
                "  next: "
                f"{next_frontier.get('frontier_id')} "
                f"({route or 'no-route'})"
            )
            if isinstance(continuation, Mapping) and continuation.get("command"):
                lines.append(f"  command: {continuation['command']}")
        else:
            lines.append("  next: none")
            _extend_retained_meta_text(lines, function_payload.get("meta_ceiling"))
        for terminal in function_payload.get("terminal_frontiers", []) or []:
            if not isinstance(terminal, Mapping):
                continue
            reason = terminal.get("terminal_reason") or "terminal"
            lines.append(
                f"  terminal: {terminal.get('frontier_id')} ({reason})"
            )
    return "\n".join(lines)


def synthesize_retained_frontier_meta_ceiling(
    payload: Mapping[str, Any],
    *,
    function: str | None = None,
) -> dict[str, Any]:
    """Return a reusable meta-ceiling proof for retained-frontier output."""
    if payload.get("kind") == "retained-frontiers-meta-ceiling":
        if function and payload.get("function") != function:
            return _empty_retained_meta(function)
        return dict(payload)

    entries = _retained_meta_function_entries(payload, function=function)
    if not entries:
        return _empty_retained_meta(function)
    if len(entries) > 1 and function is None:
        return {
            "kind": "retained-frontiers-meta-ceiling-set",
            "status": "multiple-functions",
            "functions": [
                synthesize_retained_frontier_meta_ceiling(entry)
                for entry in entries
            ],
        }

    entry = entries[0]
    fn = str(entry.get("function") or function or "")
    retained_status = str(
        entry.get("retained_frontiers_status")
        or entry.get("status")
        or payload.get("status")
        or ""
    )
    frontiers = [
        dict(row) for row in (entry.get("frontiers") or [])
        if isinstance(row, Mapping)
    ]
    terminals = [
        dict(row) for row in (entry.get("terminal_frontiers") or [])
        if isinstance(row, Mapping)
    ]
    combined = [*frontiers, *terminals]
    _apply_sort_window_order_common_subexpr_suppression(combined)
    suppressed_frontiers = [row for row in frontiers if row.get("terminal")]
    frontiers = [row for row in frontiers if not row.get("terminal")]
    terminals = [*terminals, *suppressed_frontiers]
    terminals = _retained_meta_enriched_terminals(frontiers, terminals)
    existing_frontier_ids = {
        str(row.get("frontier_id")) for row in frontiers
        if row.get("frontier_id")
    }
    frontiers.extend(
        _retained_terminal_source_model_semantic_recombine_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )
    existing_frontier_ids.update(
        str(row.get("frontier_id")) for row in frontiers if row.get("frontier_id")
    )
    frontiers.extend(
        _retained_terminal_stack_clean_no_anchor_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )
    existing_frontier_ids.update(
        str(row.get("frontier_id")) for row in frontiers if row.get("frontier_id")
    )
    frontiers.extend(
        _retained_terminal_draw_helper_boundary_handoff_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )
    existing_frontier_ids.update(
        str(row.get("frontier_id")) for row in frontiers if row.get("frontier_id")
    )
    frontiers.extend(
        _retained_terminal_draw_protected_expression_subhunk_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )
    next_frontier = (
        dict(entry["next_frontier"])
        if isinstance(entry.get("next_frontier"), Mapping)
        else None
    )
    if next_frontier is not None:
        closed_frontier_ids = {
            str(row.get("frontier_id")) for row in terminals
            if row.get("frontier_id")
        }
        if str(next_frontier.get("frontier_id")) in closed_frontier_ids:
            next_frontier = None
            if retained_status == "actionable" and not frontiers and terminals:
                retained_status = "all-known-frontiers-exhausted"
    consumed_stack_clean_next_frontier = _stack_clean_no_anchor_next_frontier_consumed(
        next_frontier,
        terminals,
    )
    if consumed_stack_clean_next_frontier:
        next_frontier = None
    if (
        not retained_status
        and not frontiers
        and next_frontier is None
        and terminals
    ):
        retained_status = "all-known-frontiers-exhausted"
    ranked_lanes = _retained_meta_ranked_lanes(frontiers, terminals)
    if ranked_lanes:
        return {
            "kind": "retained-frontiers-meta-ceiling",
            "function": fn,
            "status": "actionable",
            "retained_frontiers_status": retained_status or "actionable",
            "next_frontier": ranked_lanes[0],
            "summary": dict(entry.get("summary") or {}),
            "closed_families": _retained_meta_closed_families(terminals),
            "terminal_groups": _retained_meta_terminal_groups(terminals),
            "ranked_next_lanes": ranked_lanes,
        }

    if consumed_stack_clean_next_frontier and retained_status == "actionable":
        retained_status = "all-known-frontiers-exhausted"

    if (
        retained_status != "all-known-frontiers-exhausted"
        or next_frontier is not None
        or not terminals
    ):
        return _empty_retained_meta(fn)

    groups = _retained_meta_terminal_groups(terminals)
    terminal_proof = _retained_meta_terminal_proof(terminals, groups)
    return {
        "kind": "retained-frontiers-meta-ceiling",
        "function": fn,
        "status": "terminal-current-source-shape-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        ),
        "terminal_blocker": "current-source-shape-ceiling",
        "source_shape_exhausted": True,
        "retained_frontiers_status": retained_status,
        "next_frontier": None,
        "summary": dict(entry.get("summary") or {}),
        "closed_families": _retained_meta_closed_families(terminals),
        "terminal_groups": groups,
        "ranked_next_lanes": [],
        "terminal_proof": terminal_proof,
    }


def retained_frontier_meta_ceiling_for_function(
    payload: Mapping[str, Any],
    *,
    function: str,
) -> dict[str, Any]:
    return synthesize_retained_frontier_meta_ceiling(payload, function=function)


def retained_frontier_meta_ceiling_from_payloads(
    payloads: Iterable[Mapping[str, Any]],
    *,
    function: str,
) -> dict[str, Any]:
    payload_list = [
        payload for payload in payloads
        if isinstance(payload, Mapping)
    ]
    has_retained_payload = any(
        _retained_meta_function_entries(payload, function=function)
        for payload in payload_list
    )

    raw_frontiers: list[dict[str, Any]] = []
    raw_simplify_exhaustions: list[dict[str, Any]] = []
    payload_count = 0
    for index, payload in enumerate(payload_list):
        payload_count += 1
        artifact = Path(f"evidence-payload-{index}.json")
        for frontier in _extract_frontiers(payload, artifact=artifact):
            if frontier.get("function") != function:
                continue
            if (
                not has_retained_payload
                and not _is_common_subexpr_residual_handoff_frontier(frontier)
                and not _is_direct_retained_meta_ceiling_frontier(frontier)
            ):
                continue
            raw_frontiers.append(frontier)
        raw_simplify_exhaustions.extend(
            _extract_retained_simplify_exhaustions(payload, artifact=artifact)
        )
    if not raw_frontiers:
        return _empty_retained_meta(function)

    _apply_retained_simplify_exhaustions(raw_frontiers, raw_simplify_exhaustions)
    merged = _merge_frontiers(raw_frontiers)
    _apply_terminal_suppression(merged)
    function_frontiers = [row for row in merged if row.get("function") == function]
    existing_frontier_ids = {
        str(frontier.get("frontier_id")) for frontier in function_frontiers
        if frontier.get("frontier_id")
    }
    terminals = [frontier for frontier in function_frontiers if frontier.get("terminal")]
    function_frontiers.extend(
        _retained_terminal_source_model_semantic_recombine_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )
    existing_frontier_ids.update(
        str(frontier.get("frontier_id"))
        for frontier in function_frontiers
        if frontier.get("frontier_id")
    )
    terminals = [frontier for frontier in function_frontiers if frontier.get("terminal")]
    function_frontiers.extend(
        _retained_terminal_stack_clean_no_anchor_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )
    existing_frontier_ids.update(
        str(frontier.get("frontier_id"))
        for frontier in function_frontiers
        if frontier.get("frontier_id")
    )
    terminals = [frontier for frontier in function_frontiers if frontier.get("terminal")]
    function_frontiers.extend(
        _retained_terminal_draw_helper_boundary_handoff_lanes(
            terminals,
            existing_frontier_ids=existing_frontier_ids,
        )
    )

    ranked = _rank_frontiers(function_frontiers)
    for rank, frontier in enumerate(ranked, start=1):
        frontier["rank"] = rank
    unexhausted = [
        _public_frontier(frontier)
        for frontier in ranked
        if not frontier.get("terminal")
    ]
    terminal = [
        _public_frontier(frontier)
        for frontier in ranked
        if frontier.get("terminal")
    ]
    next_frontier = next(
        (
            frontier for frontier in unexhausted
            if frontier.get("actionable") and frontier.get("continuation")
        ),
        None,
    )
    status = (
        "actionable"
        if next_frontier is not None
        else "all-known-frontiers-exhausted"
    )
    payload = {
        "status": status,
        "artifact_count": payload_count,
        "parsed_artifact_count": payload_count,
        "skipped_artifacts": [],
        "functions": [
            {
                "function": function,
                "current_match_percent": None,
                "frontiers": unexhausted,
                "terminal_frontiers": terminal,
                "next_frontier": next_frontier,
                "summary": {
                    "unexhausted_count": len(unexhausted),
                    "terminal_count": len(terminal),
                    "suppressed_by_terminal_count": sum(
                        1 for frontier in terminal
                        if frontier.get("suppressed_by_terminal")
                    ),
                },
            }
        ],
        "next_frontier": next_frontier,
    }
    return synthesize_retained_frontier_meta_ceiling(payload, function=function)


def retained_frontier_meta_rank(meta: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """Return the ordering key used to choose newer retained-meta evidence."""
    return _retained_meta_rank(meta)


def _empty_retained_meta(function: str | None) -> dict[str, Any]:
    return {
        "kind": "retained-frontiers-meta-ceiling",
        "function": function,
        "status": "not-present",
        "ranked_next_lanes": [],
    }


def _is_direct_retained_meta_ceiling_frontier(
    frontier: Mapping[str, Any],
) -> bool:
    if not (
        frontier.get("terminal")
        or frontier.get("actionable")
        or _retained_meta_continuation_has_action(frontier.get("continuation"))
    ):
        return False
    family = str(frontier.get("family_id") or "")
    kind = str(frontier.get("kind") or "")
    suppression = str(frontier.get("suppression_family") or "")
    route = str(_nested_value(frontier, ("continuation", "route")) or "")
    searchable = " ".join(
        part for part in (family, kind, suppression, route) if part
    )
    if (
        kind == "retained-source-case-c-target-live-range-interference"
        or "target_live_range" in searchable
        or "target-live-range" in searchable
    ):
        return _is_direct_sort_target_live_range_terminal(frontier)
    if frontier.get("function") != _SORT_FUNCTION:
        return False
    if family == _SORT_DIRECT_SCORE_SOURCE_FAMILY:
        return True
    if "recombine" in searchable:
        return True
    if _frontier_concrete_protected_loss_terminal(frontier):
        return True
    proof = frontier.get("source_model_proof")
    synthesis = (
        proof.get("source_family_synthesis")
        if isinstance(proof, Mapping)
        else None
    )
    return bool(
        isinstance(synthesis, Mapping)
        and (
            isinstance(synthesis.get("recombine_negative_evidence"), Mapping)
            or isinstance(synthesis.get("protected_structural_synthesis"), Mapping)
        )
    )


def _is_direct_sort_target_live_range_terminal(
    frontier: Mapping[str, Any],
) -> bool:
    if frontier.get("function") != _SORT_FUNCTION:
        return False
    if not frontier.get("terminal"):
        return False
    if frontier.get("status") == "materialized-not-scored":
        return False
    metrics = frontier.get("metrics")
    if not isinstance(metrics, Mapping):
        return False
    evaluated = _to_int(metrics.get("evaluated_probe_count"))
    unscoreable = _to_int(metrics.get("unscoreable_count")) or 0
    if evaluated is None or evaluated <= unscoreable:
        return False
    exact = _to_int(metrics.get("exact_count"))
    return exact in (None, 0)


def _retained_meta_function_entries(
    payload: Mapping[str, Any],
    *,
    function: str | None,
) -> list[Mapping[str, Any]]:
    functions = payload.get("functions")
    if isinstance(functions, list):
        entries = [
            row for row in functions
            if isinstance(row, Mapping)
            and (function is None or row.get("function") == function)
        ]
        return entries
    if _retained_meta_is_function_entry(payload):
        if function is None or payload.get("function") == function:
            return [payload]
    return []


def _retained_meta_is_function_entry(payload: Mapping[str, Any]) -> bool:
    return (
        isinstance(payload.get("function"), str)
        and (
            isinstance(payload.get("frontiers"), list)
            or isinstance(payload.get("terminal_frontiers"), list)
            or "next_frontier" in payload
        )
    )


def _retained_meta_enriched_terminals(
    frontiers: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    proof_sources = [
        row for row in [*frontiers, *terminals]
        if isinstance(row, Mapping)
        and isinstance(row.get("source_model_proof"), Mapping)
    ]
    out: list[dict[str, Any]] = []
    for terminal in terminals:
        enriched = dict(terminal)
        source = _retained_meta_matching_source_model_proof(enriched, proof_sources)
        if source is not None:
            _retained_meta_merge_source_model_proof(enriched, source)
            for key in (
                "exhausted_dimensions",
                "candidate_count",
                "scored_count",
                "best_score_summary",
            ):
                if enriched.get(key) is None and source.get(key) is not None:
                    enriched[key] = source[key]
        _merge_stack_clean_terminal_summary_fields_for_row(enriched)
        _retained_meta_ensure_unsupported_source_expression_class(enriched)
        out.append(enriched)
    return out


def _retained_meta_matching_source_model_proof(
    terminal: Mapping[str, Any],
    proof_sources: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    terminal_function = _non_empty_str(terminal.get("function"))
    terminal_force = _frontier_force_for_matching(terminal)
    for source in proof_sources:
        if source is terminal:
            continue
        if terminal_function and source.get("function") != terminal_function:
            continue
        source_force = _frontier_force_for_matching(source)
        if terminal_force and source_force and terminal_force != source_force:
            continue
        return source
    return None


def _retained_meta_merge_source_model_proof(
    terminal: dict[str, Any],
    source: Mapping[str, Any],
) -> None:
    incoming = source.get("source_model_proof")
    if not isinstance(incoming, Mapping):
        return
    existing = terminal.get("source_model_proof")
    if not isinstance(existing, Mapping):
        terminal["source_model_proof"] = _source_model_proof_without_stale_blockers(
            incoming
        )
        return
    merged = dict(existing)
    incoming_stack_chain = _retained_terminal_proof_draw_stack_terminal_chain(incoming)
    existing_stack_chain = _retained_terminal_proof_draw_stack_terminal_chain(existing)
    if incoming_stack_chain and existing_stack_chain:
        incoming_priority = _retained_terminal_proof_selection_key(source, incoming)
        existing_priority = _retained_terminal_proof_selection_key(terminal, existing)
    elif incoming_stack_chain != existing_stack_chain:
        incoming_priority = existing_priority = (0, 0, 0, 0)
    else:
        incoming_priority = _source_model_proof_priority(incoming)
        existing_priority = _source_model_proof_priority(existing)
    if incoming_priority > existing_priority:
        for key in (
            "next_unsupported_source_model",
            "next_unsupported_source_family",
            "next_unsupported_source_spans",
            "source_family_synthesis",
            "attempted_equivalence_classes",
            "candidate_scores",
            "retained_scored_probes",
            "source_hunks_by_candidate",
            "terminal_blockers",
            "exhausted_source_dimension",
            "exhausted_dimensions",
            "terminal_reason",
            "kind",
            "unsupported_source_expression_class",
            "target_score",
            "expression_score",
        ):
            value = incoming.get(key)
            if value is not None:
                merged[key] = value
    for key, value in incoming.items():
        if value is None:
            continue
        if key not in merged or not merged.get(key):
            merged[key] = value
            continue
        if (
            key in {"expression_anchors", "target_anchors", "residual_blocker_targets"}
            and isinstance(value, list)
            and len(value) > len(merged.get(key) or [])
        ):
            merged[key] = value
    terminal["source_model_proof"] = _source_model_proof_without_stale_blockers(merged)


def _source_model_proof_priority(
    proof: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    synthesis = proof.get("source_family_synthesis")
    exhausted = _source_model_consumed_dimension_ids(proof)
    concrete_score_rows = 1 if _source_model_proof_has_scored_evidence(proof) else 0
    stage_rank = _source_model_next_unsupported_stage_rank(
        proof
    ) or _source_model_proof_stage_rank(proof, exhausted)
    evidence_rank = 0
    if isinstance(synthesis, Mapping) and synthesis.get("evidence_status") in {
        "artifact-synthesis-data",
        "artifact-score-rows",
    }:
        evidence_rank = 2
    elif exhausted or concrete_score_rows:
        evidence_rank = 1
    elif proof.get("next_unsupported_source_model"):
        evidence_rank = 0
    return (stage_rank, evidence_rank, concrete_score_rows, len(exhausted))


def _source_model_next_unsupported_stage_rank(proof: Mapping[str, Any]) -> int:
    has_explicit_next = any(
        _source_model_proof_string(proof, key)
        for key in (
            "next_unsupported_source_model",
            "next_unsupported_source_family",
            "next_unsupported_source_dimension",
        )
    )
    if not has_explicit_next:
        return 0
    return _source_model_proof_stage_rank(proof, set())


def _source_model_proof_direct_sources(
    proof: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [proof]
    source_model_proof = proof.get("source_model_proof")
    if isinstance(source_model_proof, Mapping):
        sources.append(source_model_proof)
    for source in list(sources):
        synthesis = source.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            sources.append(synthesis)
    return sources


def _source_model_proof_direct_string(
    proof: Mapping[str, Any],
    key: str,
) -> str | None:
    for source in _source_model_proof_direct_sources(proof):
        value = _non_empty_str(source.get(key))
        if value is not None:
            return value
    return None


def _source_model_proof_direct_strings(
    proof: Mapping[str, Any],
    key: str,
) -> set[str]:
    out: set[str] = set()
    for source in _source_model_proof_direct_sources(proof):
        value = source.get(key)
        text = _non_empty_str(value)
        if text is not None:
            out.add(text)
        out.update(_string_items(value))
    return out


def _sort_direct_source_model_proof_stage_rank(
    proof: Mapping[str, Any],
) -> int | None:
    next_model = _source_model_proof_direct_string(
        proof,
        "next_unsupported_source_model",
    )
    next_family = _source_model_proof_direct_string(
        proof,
        "next_unsupported_source_family",
    )
    next_dimension = _source_model_proof_direct_string(
        proof,
        "next_unsupported_source_dimension",
    )
    terminal_reasons = _source_model_proof_direct_strings(proof, "terminal_reason")
    exhausted_dimensions = _source_model_proof_direct_strings(
        proof,
        "exhausted_source_dimension",
    )
    if (
        next_model == _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
        or next_family
        == _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
        or next_dimension
        == _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        or _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
        in terminal_reasons
        or _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        in exhausted_dimensions
    ):
        return 15
    if (
        next_model
        == _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_MODEL
        or next_family
        == _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY
        or next_dimension
        == _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        or _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_REASON
        in terminal_reasons
        or _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        in exhausted_dimensions
    ):
        return 14
    if (
        next_model == _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_MODEL
        or next_family == _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
        or next_dimension == _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
        or _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_TERMINAL_REASON
        in terminal_reasons
        or _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
        in exhausted_dimensions
    ):
        return 13
    if (
        next_model == _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_MODEL
        or next_family
        == _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
        or next_dimension
        == _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION
        or _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_TERMINAL_REASON
        in terminal_reasons
        or _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION
        in exhausted_dimensions
    ):
        return 12
    return None


def _source_model_proof_stage_rank(
    proof: Mapping[str, Any],
    exhausted: set[str] | None = None,
) -> int:
    if exhausted is None:
        exhausted = _source_model_proof_dimension_ids(proof)
    next_model = _source_model_proof_string(
        proof,
        "next_unsupported_source_model",
    )
    next_family = _source_model_proof_string(
        proof,
        "next_unsupported_source_family",
    )
    next_dimension = _source_model_proof_string(
        proof,
        "next_unsupported_source_dimension",
    )
    direct_sort_stage = _sort_direct_source_model_proof_stage_rank(proof)
    if (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION in exhausted
        or next_dimension == _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        or next_model == _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL
        or next_family == _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    ):
        return 16
    if (
        _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION in exhausted
        or next_dimension == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        or next_model == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
        or next_family == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
        or next_model
        == _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
        or next_family
        == _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    ):
        return 15
    if (
        _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION in exhausted
        or next_dimension == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        or next_model == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
        or next_family == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    ):
        return 14
    if (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION in exhausted
        or next_dimension == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        or next_family == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
    ):
        return 13
    if (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION in exhausted
        or next_dimension == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        or next_model == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        or next_family == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        or next_model == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_MODEL
        or next_family == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    ):
        return 12
    if (
        _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION in exhausted
        or next_dimension == _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION
        or next_model == _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_MODEL
        or next_family == _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY
    ):
        return 11
    if (
        _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION in exhausted
        or next_dimension == _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
        or next_model == _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_MODEL
        or next_family == _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_FAMILY
    ):
        return 10
    if (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION in exhausted
        or next_model == _DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
        or next_family == _DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    ):
        return 9
    if (
        next_dimension == DRAW_POST_SOURCE_CONTEXT_DIMENSION
        or next_family == DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY
        or next_model == DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_MODEL
    ):
        return 8
    if (
        _DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION in exhausted
        or next_model == _DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_MODEL
        or next_family == _DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY
    ):
        return 7
    if (
        _DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_DIMENSION in exhausted
        or next_model == _DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_EXHAUSTED_NEXT_MODEL
        or next_family
        == _DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_EXHAUSTED_NEXT_FAMILY
    ):
        return 6
    if (
        _DRAW_COUPLED_FPR_LIFETIME_DIMENSION in exhausted
        or next_model == _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL
        or _source_model_proof_has_unsupported_source_expression_class(
            proof,
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS,
        )
    ):
        return 5
    if exhausted & (
        set(_DRAW_SOURCE_FAMILY_DIMENSIONS)
        | {
            "draw-row-offset-owner-scale",
            "draw-pcode-fsubs-protected-anchor",
        }
    ):
        return 4
    if direct_sort_stage is not None:
        return direct_sort_stage
    if (
        _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        in exhausted
        or next_dimension
        == _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        or next_model
        == _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
        or next_family
        == _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    ):
        return 15
    if (
        _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        in exhausted
        or next_dimension
        == _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        or next_model
        == _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_MODEL
        or next_family
        == _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY
    ):
        return 14
    if (
        _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION in exhausted
        or next_dimension == _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
        or next_model == _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_MODEL
        or next_family == _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
    ):
        return 13
    if (
        _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION in exhausted
        or next_dimension
        == _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION
        or next_model
        == _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_MODEL
        or next_family
        == _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
    ):
        return 12
    if (
        _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION in exhausted
        or next_model
        == _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
        or next_family
        == _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    ):
        return 11
    if (
        _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION in exhausted
        or next_model
        == _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_MODEL
        or next_family
        == _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    ):
        return 10
    if (
        _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION in exhausted
        or next_model
        == _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL
        or next_family
        == _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
    ):
        return 9
    if (
        _SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION in exhausted
        or next_model == _SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL
        or next_family == _SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY
    ):
        return 8
    if (
        next_family == _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY
        or next_model == _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL
        or _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION in exhausted
    ):
        return 7
    if (
        next_family == _SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
        or next_model == _SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL
    ):
        return 6
    if (
        _SORT_FULL_SELECTION_SWAP_DIMENSION in exhausted
        and not _source_model_proof_has_blocker(
            proof,
            _SORT_FULL_SELECTION_SWAP_NOT_MATERIALIZED_BLOCKER,
        )
    ):
        return 5
    if "sort-protected-loss-init-lifetime" in exhausted:
        return 4
    if any(
        dimension.startswith("sort-semantic-")
        for dimension in exhausted
    ):
        return 3
    if any(dimension.startswith("sort-natural-") for dimension in exhausted):
        return 2
    if exhausted:
        return 1
    if next_model:
        return 1
    return 0


def _source_model_proof_dimension_ids(proof: Mapping[str, Any]) -> set[str]:
    synthesis = proof.get("source_family_synthesis")
    sources: list[Any] = [
        proof.get("attempted_equivalence_classes"),
        proof.get("exhausted_source_dimension"),
        proof.get("exhausted_dimensions"),
    ]
    if isinstance(synthesis, Mapping):
        sources.extend([
            synthesis.get("attempted_equivalence_classes"),
            synthesis.get("exhausted_source_dimension"),
            synthesis.get("exhausted_dimensions"),
            synthesis.get("equivalence_class_details"),
        ])
    out: set[str] = set()
    for source in sources:
        item = _non_empty_str(source)
        if item is not None:
            out.add(item)
        if isinstance(source, list):
            for row in source:
                if isinstance(row, Mapping) and row.get("dimension_id"):
                    out.add(str(row["dimension_id"]))
                elif isinstance(row, str) and row:
                    out.add(row)
    return out


def _source_model_consumed_dimension_ids(proof: Mapping[str, Any]) -> set[str]:
    synthesis = proof.get("source_family_synthesis")
    sources: list[Any] = [
        proof.get("exhausted_source_dimension"),
        proof.get("exhausted_dimensions"),
    ]
    if isinstance(synthesis, Mapping):
        sources.extend([
            synthesis.get("exhausted_source_dimension"),
            synthesis.get("exhausted_dimensions"),
            synthesis.get("equivalence_class_details"),
        ])
    out: set[str] = set()
    for source in sources:
        item = _non_empty_str(source)
        if item is not None:
            out.add(item)
        if isinstance(source, list):
            for row in source:
                if isinstance(row, Mapping):
                    dimension = _non_empty_str(row.get("dimension_id"))
                    if (
                        dimension is not None
                        and _source_model_dimension_row_has_consumed_evidence(row)
                    ):
                        out.add(dimension)
                elif isinstance(row, str) and row:
                    out.add(row)
    if (
        not _source_model_next_unsupported_stage_rank(proof)
        and _source_model_proof_has_scored_evidence(proof)
    ):
        for source in (
            proof.get("attempted_equivalence_classes"),
            synthesis.get("attempted_equivalence_classes")
            if isinstance(synthesis, Mapping)
            else None,
        ):
            item = _non_empty_str(source)
            if item is not None:
                out.add(item)
            if isinstance(source, list):
                out.update(str(row) for row in source if isinstance(row, str) and row)
    return out


def _source_model_dimension_row_has_consumed_evidence(row: Mapping[str, Any]) -> bool:
    for key in ("scored_count", "candidate_count"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value > 0:
                return True
            if value == 0:
                return False
    for key in ("scored_candidate_ids", "candidate_ids"):
        value = row.get(key)
        if isinstance(value, list):
            return bool(value)
    status = _non_empty_str(row.get("status")) or ""
    if "continuation-exhausted" in status:
        return False
    if "scored" in status:
        return True
    return True


def _source_model_proof_has_scored_evidence(proof: Mapping[str, Any]) -> bool:
    synthesis = proof.get("source_family_synthesis")
    for source in (proof, synthesis if isinstance(synthesis, Mapping) else None):
        if not isinstance(source, Mapping):
            continue
        for key in ("candidate_scores", "retained_scored_probes"):
            value = source.get(key)
            if isinstance(value, list) and value:
                return True
        exhausted = source.get("exhausted_dimensions")
        if isinstance(exhausted, list):
            for row in exhausted:
                if (
                    isinstance(row, Mapping)
                    and _source_model_dimension_row_has_consumed_evidence(row)
                ):
                    return True
    return False


def _source_model_proof_retained_score_count(proof: Mapping[str, Any]) -> int:
    synthesis = proof.get("source_family_synthesis")
    count = 0
    for source in (proof, synthesis if isinstance(synthesis, Mapping) else None):
        if not isinstance(source, Mapping):
            continue
        retained = source.get("retained_scored_probes")
        if isinstance(retained, list):
            count = max(count, len(retained))
    return count


def _source_model_proof_string(
    proof: Mapping[str, Any],
    key: str,
) -> str | None:
    value = _non_empty_str(proof.get(key))
    if value is not None:
        return value
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        value = _non_empty_str(synthesis.get(key))
        if value is not None:
            return value
    for value in _nested_strings_for_key(proof, key):
        if value:
            return value
    return None


def _nested_strings_for_key(raw: Any, key: str) -> list[str]:
    if isinstance(raw, Mapping):
        strings: list[str] = []
        for item_key, value in raw.items():
            if item_key == key and isinstance(value, str):
                strings.append(value)
            if isinstance(value, (Mapping, list, tuple)):
                strings.extend(_nested_strings_for_key(value, key))
        return strings
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        strings: list[str] = []
        for value in raw:
            strings.extend(_nested_strings_for_key(value, key))
        return strings
    return []


def _source_model_proof_has_blocker(
    proof: Mapping[str, Any],
    blocker: str,
) -> bool:
    for source in (proof, proof.get("source_family_synthesis")):
        if not isinstance(source, Mapping):
            continue
        for raw in source.get("terminal_blockers") or []:
            if _terminal_blocker_reason(raw) == blocker:
                return True
    return False


def _source_model_proof_has_unsupported_source_expression_class(
    proof: Mapping[str, Any],
    unsupported_class: str,
) -> bool:
    for source in (proof, proof.get("source_family_synthesis")):
        if not isinstance(source, Mapping):
            continue
        if _non_empty_str(source.get("unsupported_source_expression_class")) == (
            unsupported_class
        ):
            return True
    return False


def _terminal_blocker_reason(raw: Any) -> str | None:
    if isinstance(raw, Mapping):
        return _non_empty_str(raw.get("reason") or raw.get("terminal_blocker"))
    return _non_empty_str(raw)


def _source_model_proof_without_stale_blockers(
    proof: Mapping[str, Any],
) -> dict[str, Any]:
    out = dict(proof)
    next_dimension = _non_empty_str(out.get("next_unsupported_source_dimension"))
    if (
        next_dimension is not None
        and next_dimension in _source_model_proof_dimension_ids(out)
    ):
        out.pop("next_unsupported_source_dimension", None)
    if _source_model_proof_priority(out)[0] < 6:
        return out

    def filtered_blockers(raw: Any) -> list[Any] | None:
        if not isinstance(raw, list):
            return None
        return [
            row for row in raw
            if _terminal_blocker_reason(row)
            != _SORT_FULL_SELECTION_SWAP_NOT_MATERIALIZED_BLOCKER
        ]

    blockers = filtered_blockers(out.get("terminal_blockers"))
    if blockers is not None:
        out["terminal_blockers"] = blockers
    synthesis = out.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
        blockers = filtered_blockers(synthesis_out.get("terminal_blockers"))
        if blockers is not None:
            synthesis_out["terminal_blockers"] = blockers
        out["source_family_synthesis"] = synthesis_out
    return out


def _retained_meta_ensure_unsupported_source_expression_class(
    terminal: dict[str, Any],
) -> None:
    proof = terminal.get("source_model_proof")
    if not isinstance(proof, Mapping):
        return
    proof = dict(proof)
    unsupported = _retained_meta_unsupported_source_expression_class(terminal)
    if unsupported:
        proof.setdefault("unsupported_source_expression_class", unsupported)
        terminal["unsupported_source_expression_class"] = unsupported
    if (
        unsupported == _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        and not _non_empty_str(proof.get("next_unsupported_source_model"))
    ):
        proof["next_unsupported_source_model"] = _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL
    terminal["source_model_proof"] = proof


def _retained_meta_ranked_lanes(
    frontiers: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    terminal_ids = {
        str(row.get("frontier_id")) for row in terminals
        if row.get("frontier_id")
    }
    terminal_signatures = {
        _retained_meta_suppression_signature(row)
        for row in terminals
        if _retained_meta_suppression_signature(row) is not None
    }
    terminal_stage = max(
        (_retained_meta_terminal_source_model_stage(row) for row in terminals),
        default=0,
    )
    stack_clean_completed_terminals = [
        row for row in terminals
        if _frontier_closes_stack_clean_no_anchor_recovery(row)
    ]
    post_stack_clean_completed_terminals = [
        row for row in terminals
        if _retained_post_stack_clean_no_anchor_source_shape_completed(row)
        or _retained_post_stack_loop_callsite_source_context_completed(row)
    ]
    lanes: list[dict[str, Any]] = []
    for row in frontiers:
        if row.get("terminal"):
            continue
        if row.get("frontier_id") in terminal_ids:
            continue
        if _retained_meta_stack_clean_no_anchor_lane(row) and any(
            _stack_clean_no_anchor_terminal_matches_lane(terminal, row)
            for terminal in stack_clean_completed_terminals
        ):
            continue
        if (
            _retained_meta_stack_clean_no_anchor_lane(row)
            and post_stack_clean_completed_terminals
        ):
            continue
        signature = _retained_meta_suppression_signature(row)
        if (
            signature is not None
            and signature in terminal_signatures
            and not _retained_meta_stack_clean_no_anchor_lane(row)
        ):
            continue
        lane_stage = _retained_meta_lane_source_model_stage(row)
        if (
            terminal_stage
            and 0 < lane_stage < terminal_stage
            and not _retained_meta_stack_clean_no_anchor_lane(row)
        ):
            continue
        if not _retained_meta_lane_actionable(row):
            continue
        lanes.append(_retained_meta_public_lane(row))
    return sorted(lanes, key=_retained_meta_lane_rank_key)


def _retained_meta_stack_clean_no_anchor_lane(row: Mapping[str, Any]) -> bool:
    if row.get("dimension_id") == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION:
        return True
    if row.get("source_model_layer_dimension_id") == (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    ):
        return True
    if row.get("stack_clean_no_anchor_evidence") is not None:
        return True
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        if proof.get("stack_clean_no_anchor_evidence") is not None:
            return True
        if proof.get("next_unsupported_source_dimension") == (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ):
            return True
    continuation = row.get("continuation")
    if isinstance(continuation, Mapping):
        return (
            continuation.get("route")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            or continuation.get("dimension_id")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            or continuation.get("next_unsupported_source_dimension")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
    return False


def _stack_clean_no_anchor_next_frontier_consumed(
    next_frontier: Mapping[str, Any] | None,
    terminals: Sequence[Mapping[str, Any]],
) -> bool:
    if not isinstance(next_frontier, Mapping):
        return False
    if not _retained_meta_stack_clean_no_anchor_recovery_lane(next_frontier):
        return False
    return any(
        _stack_clean_no_anchor_terminal_matches_lane(terminal, next_frontier)
        for terminal in terminals
        if _frontier_closes_stack_clean_no_anchor_recovery(terminal)
    )


def _retained_meta_stack_clean_no_anchor_recovery_lane(
    row: Mapping[str, Any],
) -> bool:
    if row.get("dimension_id") == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION:
        return True
    if row.get("source_model_layer_dimension_id") == (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    ):
        return True
    continuation = row.get("continuation")
    if isinstance(continuation, Mapping):
        return (
            continuation.get("route")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            or continuation.get("dimension_id")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            or continuation.get("next_unsupported_source_dimension")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
    return False


def _retained_terminal_source_model_semantic_recombine_lanes(
    terminals: Sequence[Mapping[str, Any]],
    *,
    existing_frontier_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    terminal_rows = [row for row in terminals if isinstance(row, Mapping)]
    if any(_frontier_closes_sort_semantic_recombine(row) for row in terminal_rows):
        return []

    existing = set(existing_frontier_ids or set())
    lanes: list[dict[str, Any]] = []
    for terminal in terminal_rows:
        proof = terminal.get("source_model_proof")
        if not isinstance(proof, Mapping):
            continue
        for semantic in _retained_terminal_semantic_recombine_blocks(proof):
            candidates = _retained_semantic_recombine_actionable_candidates(
                semantic
            )
            for candidate in candidates:
                lane = _retained_semantic_recombine_candidate_lane(
                    terminal,
                    semantic,
                    candidate,
                )
                if lane is None:
                    continue
                frontier_id = str(lane.get("frontier_id") or "")
                if not frontier_id or frontier_id in existing:
                    continue
                existing.add(frontier_id)
                lanes.append(lane)
    return lanes


def _retained_terminal_stack_clean_no_anchor_lanes(
    terminals: Sequence[Mapping[str, Any]],
    *,
    existing_frontier_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    terminal_rows = [row for row in terminals if isinstance(row, Mapping)]
    if _retained_stack_clean_no_anchor_terminal_completed(
        terminal_rows
    ) or any(
        _retained_post_stack_clean_no_anchor_source_shape_completed(row)
        or _retained_post_stack_loop_callsite_source_context_completed(row)
        for row in terminal_rows
    ):
        return []
    existing = set(existing_frontier_ids or set())
    lanes: list[dict[str, Any]] = []
    for terminal in terminal_rows:
        evidence = _retained_stack_clean_no_anchor_evidence(terminal)
        if evidence is None:
            continue
        lane = _retained_stack_clean_no_anchor_lane(terminal, evidence)
        if lane is None:
            continue
        frontier_id = str(lane.get("frontier_id") or "")
        if not frontier_id or frontier_id in existing:
            continue
        existing.add(frontier_id)
        lanes.append(lane)
    return lanes


def _retained_terminal_draw_helper_boundary_handoff_lanes(
    terminals: Sequence[Mapping[str, Any]],
    *,
    existing_frontier_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    terminal_rows = [row for row in terminals if isinstance(row, Mapping)]
    if _retained_draw_helper_boundary_handoff_completed(terminal_rows):
        return []
    existing = set(existing_frontier_ids or set())
    lanes: list[dict[str, Any]] = []
    for terminal in terminal_rows:
        evidence = _retained_draw_helper_boundary_handoff_evidence(terminal)
        if evidence is None:
            continue
        lane = _retained_draw_helper_boundary_handoff_lane(terminal, evidence)
        if lane is None:
            continue
        frontier_id = str(lane.get("frontier_id") or "")
        if not frontier_id or frontier_id in existing:
            continue
        existing.add(frontier_id)
        lanes.append(lane)
    return lanes


def _retained_terminal_draw_protected_expression_subhunk_lanes(
    terminals: Sequence[Mapping[str, Any]],
    *,
    existing_frontier_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    terminal_rows = [row for row in terminals if isinstance(row, Mapping)]
    if _retained_draw_protected_expression_reconcile_completed(terminal_rows):
        return []
    existing = set(existing_frontier_ids or set())
    lanes: list[dict[str, Any]] = []
    for terminal in terminal_rows:
        evidence = _retained_draw_protected_expression_subhunk_evidence(terminal)
        if evidence is None:
            continue
        lane = _retained_draw_protected_expression_subhunk_lane(terminal, evidence)
        if lane is None:
            continue
        frontier_id = str(lane.get("frontier_id") or "")
        if not frontier_id or frontier_id in existing:
            continue
        existing.add(frontier_id)
        lanes.append(lane)
    return lanes


def _retained_draw_protected_expression_reconcile_completed(
    terminals: Sequence[Mapping[str, Any]],
) -> bool:
    return any(
        _frontier_closes_draw_protected_expression_reconcile(terminal)
        for terminal in terminals
        if isinstance(terminal, Mapping)
    )


def _retained_draw_protected_expression_subhunk_evidence(
    terminal: Mapping[str, Any],
) -> dict[str, Any] | None:
    if terminal.get("function") != "mnDiagram_DrawCellNumber":
        return None
    blockers = _retained_draw_protected_expression_blockers(terminal)
    if not {
        "manual-subhunk-range-required",
        "all-recombines-lost-protected-anchors",
    }.intersection(blockers):
        return None
    rows = _retained_draw_protected_expression_candidate_rows(terminal)
    missing_evidence = False
    for row in rows:
        candidate_id = _non_empty_str(row.get("candidate_id"))
        dimension_id = (
            _non_empty_str(row.get("dimension_id"))
            or _dimension_from_candidate_id(candidate_id)
        )
        if not candidate_id or not _retained_draw_row_delta_candidate(
            candidate_id,
            dimension_id,
        ):
            continue
        target_score = _mapping_or_none(row.get("target_score")) or {}
        expression_score = _mapping_or_none(row.get("expression_score")) or {}
        target_matched = _score_matched(row, target_score, "target")
        expression_matched = _score_matched(row, expression_score, "expression")
        expression_targeted = _score_targeted(row, expression_score, "expression")
        normalized = _row_normalized_diff_lines(row)
        expression_false_positive = (
            _to_int(expression_score.get("false_positive_virtual_id_hit_count"))
            or 0
        ) > 0
        if target_matched < 1:
            continue
        if expression_matched != 0:
            continue
        if expression_targeted in (None, 0):
            continue
        if normalized != 0:
            continue
        if not expression_false_positive and not _retained_draw_expression_missing(
            expression_score
        ):
            continue
        source_retained = _non_empty_str(row.get("source_retained"))
        pcdump_path = _non_empty_str(row.get("pcdump_path"))
        source_hunks = row.get("source_hunks")
        if not (
            source_retained
            and pcdump_path
            and isinstance(source_hunks, list)
            and source_hunks
        ):
            missing_evidence = True
            continue
        evidence = {
            "candidate_id": candidate_id,
            "dimension_id": dimension_id or "draw-row-translation-scale-split",
            "source_retained": source_retained,
            "pcdump_path": pcdump_path,
            "source_hunks": list(source_hunks),
            "target_score": dict(target_score),
            "expression_score": dict(expression_score),
            "normalized_diff_lines": normalized,
            "terminal_blockers": sorted(blockers),
        }
        manual_subhunks = _retained_draw_manual_subhunks(source_hunks)
        if manual_subhunks:
            evidence["manual_subhunks"] = manual_subhunks
            evidence["protected_subhunks"] = manual_subhunks
        return evidence
    if missing_evidence:
        _append_source_model_terminal_blocker(
            terminal,
            "draw-protected-expression-subhunk-missing-source-evidence",
        )
    return None


def _retained_draw_protected_expression_subhunk_lane(
    terminal: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any] | None:
    function = _non_empty_str(terminal.get("function"))
    candidate_id = _non_empty_str(evidence.get("candidate_id"))
    source_retained = _non_empty_str(evidence.get("source_retained"))
    pcdump_path = _non_empty_str(evidence.get("pcdump_path"))
    source_hunks = evidence.get("source_hunks")
    if not (
        function
        and candidate_id
        and source_retained
        and pcdump_path
        and isinstance(source_hunks, list)
        and source_hunks
    ):
        return None
    final_force = _frontier_force_for_matching(terminal)
    attempted = dict(final_force)
    dimension_id = (
        _non_empty_str(evidence.get("dimension_id"))
        or "draw-row-translation-scale-split"
    )
    frontier_id = _frontier_id(
        function,
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        ("candidate", candidate_id),
        ("force", final_force),
    )
    command = _retained_draw_protected_expression_command(
        function=function,
        source_retained=source_retained,
    )
    continuation: dict[str, Any] = {
        "route": _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        "candidate_id": candidate_id,
        "dimension_id": dimension_id,
        "source_retained": source_retained,
        "pcdump_path": pcdump_path,
        "source_hunks": list(source_hunks),
        "target_score": evidence.get("target_score"),
        "expression_score": evidence.get("expression_score"),
        "normalized_diff_lines": evidence.get("normalized_diff_lines"),
        "command": command,
    }
    for key in ("manual_subhunks", "protected_subhunks"):
        if evidence.get(key):
            continuation[key] = evidence[key]
    lane: dict[str, Any] = {
        "rank": None,
        "frontier_id": frontier_id,
        "function": function,
        "family_id": _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        "suppression_family": _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "terminal": False,
        "terminal_reason": None,
        "closed_by": [],
        "suppressed_by_terminal": False,
        "actionable": True,
        "attempted_targets": attempted,
        "protected_targets": {},
        "final_force_phys": dict(final_force),
        "target_hits": {},
        "protected_hits": {},
        "match_percent": terminal.get("match_percent"),
        "normalized_drift": {
            **{key: None for key in _DRIFT_KEYS},
            "normalized_diff_lines": evidence.get("normalized_diff_lines"),
        },
        "metrics": {
            "normalized_diff_lines": evidence.get("normalized_diff_lines"),
            "target_matched": _to_int(
                _mapping_or_none(evidence.get("target_score")).get("matched")
                if _mapping_or_none(evidence.get("target_score"))
                else None
            ),
            "expression_matched": _to_int(
                _mapping_or_none(evidence.get("expression_score")).get("matched")
                if _mapping_or_none(evidence.get("expression_score"))
                else None
            ),
        },
        "best_candidate": None,
        "continuation": continuation,
        "candidate_id": candidate_id,
        "dimension_id": dimension_id,
        "source_model_layer_dimension_id": dimension_id,
        "source_retained": source_retained,
        "pcdump_path": pcdump_path,
        "source_hunks": list(source_hunks),
        "target_score": evidence.get("target_score"),
        "expression_score": evidence.get("expression_score"),
        "protected_reconcile_terminal_blockers": list(
            evidence.get("terminal_blockers") or []
        ),
        "_mtime": terminal.get("_mtime") or 0.0,
        "_final_force_phys": dict(final_force),
    }
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        lane["source_model_proof"] = dict(proof)
    return lane


def _retained_draw_protected_expression_command(
    *,
    function: str,
    source_retained: str,
) -> str:
    command_parts = [
        "melee-agent",
        "debug",
        "suggest",
        "protected-expression-reconcile",
        "--expression-source",
        source_retained,
        "--expression-score-json",
        "<expression-frontier-score.json>",
        "--structural-source",
        source_retained,
        "--structural-score-json",
        "<row-delta-local-score.json>",
        "--source-hunks-json",
        "<continuation-or-source-hunks.json>",
        "--function",
        function,
        "--source-function",
        function,
        "--json",
    ]
    return " ".join(shlex.quote(part) for part in command_parts)


def _retained_draw_protected_expression_candidate_rows(
    terminal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    def merge(row: Mapping[str, Any]) -> None:
        candidate_id = _non_empty_str(row.get("candidate_id"))
        if candidate_id is None:
            return
        existing = by_id.setdefault(candidate_id, {"candidate_id": candidate_id})
        for key, value in row.items():
            if value is None:
                continue
            current = existing.get(key)
            if current in (None, [], {}):
                existing[key] = value
        metadata = row.get("validation_metadata")
        if isinstance(metadata, Mapping):
            for key in ("source_retained", "pcdump_path", "source_hunks"):
                value = metadata.get(key)
                if value is not None and existing.get(key) in (None, [], {}):
                    existing[key] = value

    for row in _source_model_candidate_score_rows(terminal):
        merge(row)
    sources: list[Mapping[str, Any]] = [terminal]
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        sources.append(proof)
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            sources.append(synthesis)
    for source in sources:
        for key in (
            "source_hunks_by_candidate",
            "retained_scored_probes",
            "ranked_retained_candidates",
            "candidate_scores",
        ):
            for row in _source_model_synthesis_mapping_list(source, key):
                merge(row)
    return list(by_id.values())


def _retained_draw_protected_expression_blockers(
    terminal: Mapping[str, Any],
) -> set[str]:
    out: set[str] = set()
    sources: list[Any] = [terminal]
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        sources.append(proof)
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            sources.append(synthesis)
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("terminal_blockers", "generation_blockers", "blockers"):
            raw = source.get(key)
            if isinstance(raw, str):
                out.add(raw)
            elif isinstance(raw, Sequence) and not isinstance(
                raw,
                (str, bytes, bytearray),
            ):
                for item in raw:
                    if isinstance(item, Mapping):
                        value = (
                            item.get("blocker")
                            or item.get("reason")
                            or item.get("terminal_blocker")
                        )
                        if isinstance(value, str) and value:
                            out.add(value)
                    elif isinstance(item, str) and item:
                        out.add(item)
    return out


def _retained_draw_row_delta_candidate(
    candidate_id: str,
    dimension_id: str | None,
) -> bool:
    return (
        "draw-row-translation-scale-split" in candidate_id
        or dimension_id == "draw-row-translation-scale-split"
    )


def _score_matched(
    row: Mapping[str, Any],
    score: Mapping[str, Any],
    prefix: str,
) -> int:
    for value in (
        score.get("matched"),
        row.get(f"{prefix}_matched"),
        row.get("matched") if prefix == "target" else None,
    ):
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    return 0


def _score_targeted(
    row: Mapping[str, Any],
    score: Mapping[str, Any],
    prefix: str,
) -> int | None:
    for value in (
        score.get("targeted"),
        row.get(f"{prefix}_targeted"),
        row.get("targeted") if prefix == "target" else None,
    ):
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    return None


def _row_normalized_diff_lines(row: Mapping[str, Any]) -> int | None:
    direct = _to_int(row.get("normalized_diff_lines"))
    if direct is not None:
        return direct
    for key in ("structural_guard", "target_score"):
        value = row.get(key)
        if isinstance(value, Mapping):
            parsed = _to_int(value.get("normalized_diff_lines"))
            if parsed is not None:
                return parsed
            guard = value.get("structural_guard")
            if isinstance(guard, Mapping):
                parsed = _to_int(guard.get("normalized_diff_lines"))
                if parsed is not None:
                    return parsed
    return None


def _retained_draw_expression_missing(score: Mapping[str, Any]) -> bool:
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return False
    for row in virtuals.values():
        if isinstance(row, Mapping) and row.get("status") == "missing-expression":
            return True
    return False


def _retained_draw_manual_subhunks(source_hunks: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for hunk in source_hunks:
        if not isinstance(hunk, Mapping):
            continue
        for key in (
            "protected_subhunks",
            "manual_subhunks",
            "continuation_subhunks",
        ):
            children = hunk.get(key)
            if isinstance(children, list):
                out.extend(child for child in children if child is not None)
    return out


def _retained_draw_source_hunks_with_protected_subhunks(
    source_hunks: Sequence[Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hunk in source_hunks:
        if not isinstance(hunk, Mapping):
            continue
        row = dict(hunk)
        if not _retained_draw_manual_subhunks([row]):
            derived = _retained_draw_row_delta_subhunks(row)
            if derived:
                row["protected_subhunks"] = derived
        out.append(row)
    return out


def _retained_draw_row_delta_subhunks(
    hunk: Mapping[str, Any],
) -> list[dict[str, Any]]:
    removed = _string_list(hunk.get("removed") or hunk.get("old_lines"))
    added = _string_list(hunk.get("added") or hunk.get("new_lines"))
    if not removed or not added:
        return []
    base_start = _to_int(hunk.get("base_start"))
    candidate_start = _to_int(hunk.get("candidate_start"))
    if base_start is None:
        old_start = _to_int(hunk.get("old_start"))
        base_start = old_start - 1 if old_start is not None else None
    if candidate_start is None:
        new_start = _to_int(hunk.get("new_start"))
        candidate_start = new_start - 1 if new_start is not None else None
    if base_start is None or candidate_start is None:
        return []
    parent_id = _non_empty_str(hunk.get("hunk_id")) or "draw-row-delta"
    subhunks: list[dict[str, Any]] = []

    old_row_source = _first_line_index(
        removed,
        ("row_offset =", "HSD_JObjGetTranslationY", "- base"),
    )
    new_delta_decl = _first_line_index(added, ("post_meta_row_delta", "f32"))
    new_delta_assign = _first_line_index(
        added,
        ("post_meta_row_delta =", "HSD_JObjGetTranslationY", "- base"),
    )
    new_row_source = _first_line_index(
        added,
        ("row_offset =", "post_meta_row_delta"),
    )
    if (
        old_row_source is not None
        and new_delta_decl is not None
        and new_delta_assign is not None
        and new_row_source is not None
    ):
        start = min(new_delta_decl, new_delta_assign, new_row_source)
        end = max(new_delta_decl, new_delta_assign, new_row_source) + 1
        subhunks.append(
            _retained_draw_make_manual_subhunk(
                parent_id=parent_id,
                suffix="row-source",
                base_start=base_start + old_row_source,
                removed=removed[old_row_source:old_row_source + 1],
                candidate_start=candidate_start + start,
                added=added[start:end],
                source_expression="row_offset",
                target_virtuals=[32],
            )
        )

    old_row_product = _first_line_index(removed, ("row_offset", "rowf"))
    new_row_product = _first_line_index(added, ("row_offset", "post_meta_row_delta", "rowf"))
    if old_row_product is not None and new_row_product is not None:
        subhunks.append(
            _retained_draw_make_manual_subhunk(
                parent_id=parent_id,
                suffix="row-product",
                base_start=base_start + old_row_product,
                removed=removed[old_row_product:old_row_product + 1],
                candidate_start=candidate_start + new_row_product,
                added=added[new_row_product:new_row_product + 1],
                source_expression="row_offset_adj",
                target_virtuals=[37],
            )
        )
    return subhunks


def _retained_draw_make_manual_subhunk(
    *,
    parent_id: str,
    suffix: str,
    base_start: int,
    removed: Sequence[str],
    candidate_start: int,
    added: Sequence[str],
    source_expression: str,
    target_virtuals: Sequence[int],
) -> dict[str, Any]:
    base_end = base_start + len(removed)
    candidate_end = candidate_start + len(added)
    return {
        "hunk_id": f"{parent_id}-{suffix}",
        "parent_hunk_id": parent_id,
        "base_start": base_start,
        "base_end": base_end,
        "candidate_start": candidate_start,
        "candidate_end": candidate_end,
        "old_start": base_start + 1,
        "old_end": base_end,
        "new_start": candidate_start + 1,
        "new_end": candidate_end,
        "removed": list(removed),
        "added": list(added),
        "old_lines": list(removed),
        "new_lines": list(added),
        "source_expression": source_expression,
        "target_virtuals": list(target_virtuals),
        "manual_subhunk": True,
    }


def _first_line_index(lines: Sequence[str], needles: Sequence[str]) -> int | None:
    for index, line in enumerate(lines):
        if all(needle in line for needle in needles):
            return index
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return value.splitlines()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item) for item in value]
    return []


def _append_source_model_terminal_blocker(
    terminal: Mapping[str, Any],
    blocker: str,
) -> None:
    if not isinstance(terminal, dict):
        return
    proof = terminal.get("source_model_proof")
    if not isinstance(proof, dict):
        proof = {}
        terminal["source_model_proof"] = proof
    blockers = list(proof.get("terminal_blockers") or [])
    if blocker not in blockers:
        blockers.append(blocker)
    proof["terminal_blockers"] = blockers
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, dict):
        synthesis_blockers = list(synthesis.get("terminal_blockers") or [])
        if blocker not in synthesis_blockers:
            synthesis_blockers.append(blocker)
        synthesis["terminal_blockers"] = synthesis_blockers


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _retained_draw_helper_boundary_handoff_completed(
    terminals: Sequence[Mapping[str, Any]],
) -> bool:
    for terminal in terminals:
        proof = terminal.get("source_model_proof")
        sources: list[Any] = [terminal]
        if isinstance(proof, Mapping):
            sources.append(proof)
            synthesis = proof.get("source_family_synthesis")
            if isinstance(synthesis, Mapping):
                sources.append(synthesis)
        if any(_retained_draw_helper_boundary_source_completed(source) for source in sources):
            return True
    return False


def _retained_draw_helper_boundary_source_completed(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    if _closed_families_include_draw_helper_boundary(raw):
        return True
    family = (
        _non_empty_str(raw.get("suppression_family"))
        or _non_empty_str(raw.get("family_id"))
    )
    terminal_reason = _non_empty_str(
        raw.get("terminal_reason") or raw.get("terminal_blocker") or raw.get("reason")
    )
    if (
        family == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
        and terminal_reason in _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS
    ):
        return True
    if (
        raw.get("next_unsupported_source_dimension")
        == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        and terminal_reason in _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS
    ):
        return True
    blockers = raw.get("terminal_blockers")
    if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes)):
        for blocker in blockers:
            if isinstance(blocker, Mapping):
                reason = _non_empty_str(
                    blocker.get("reason")
                    or blocker.get("terminal_blocker")
                    or blocker.get("blocker")
                )
            else:
                reason = _non_empty_str(blocker)
            if (
                reason in _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS
                and (
                    family == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
                    or raw.get("next_unsupported_source_dimension")
                    == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
                )
            ):
                return True
    exhausted = raw.get("exhausted_dimensions")
    if isinstance(exhausted, Sequence) and not isinstance(exhausted, (str, bytes)):
        for row in exhausted:
            if isinstance(row, Mapping):
                dimension = row.get("dimension_id")
                reason = _non_empty_str(row.get("exhaustion_reason") or row.get("reason"))
            else:
                dimension = row
                reason = None
            if (
                dimension == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
                and (
                    reason is None
                    or reason
                    in _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS
                )
            ):
                return True
    return False


def _retained_draw_helper_boundary_handoff_evidence(
    terminal: Mapping[str, Any],
) -> dict[str, Any] | None:
    if _non_empty_str(terminal.get("function")) != _DRAW_FUNCTION:
        return None
    unsupported = _retained_meta_unsupported_source_expression_class(terminal)
    if unsupported != _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS:
        return None
    proof = terminal.get("source_model_proof")
    synthesis = (
        proof.get("source_family_synthesis")
        if isinstance(proof, Mapping)
        else None
    )
    ranked = _retained_draw_helper_boundary_ranked_candidates(terminal)
    concrete_sources: list[Any] = [
        terminal,
        proof if isinstance(proof, Mapping) else None,
        synthesis if isinstance(synthesis, Mapping) else None,
        *ranked,
    ]
    if not any(
        _retained_stack_clean_no_anchor_source_completed(source)
        for source in concrete_sources
        if isinstance(source, Mapping)
    ):
        return None
    if not any(
        _retained_candidate_has_source_evidence(source)
        for source in concrete_sources
        if isinstance(source, Mapping)
    ):
        return None
    seed = next(
        (row for row in ranked if _retained_candidate_has_source_evidence(row)),
        None,
    )
    if seed is None:
        seed = ranked[0] if ranked else {}
    evidence: dict[str, Any] = {
        "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-evidence",
        "dimension_id": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "unsupported_source_expression_class": unsupported,
        "next_unsupported_source_model": (
            _retained_meta_next_unsupported_source_model(terminal)
            or _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL
        ),
        "ranked_retained_candidates": ranked,
    }
    sources = [
        terminal,
        proof if isinstance(proof, Mapping) else None,
        synthesis if isinstance(synthesis, Mapping) else None,
        seed,
    ]
    for key in (
        "source_retained",
        "pcdump_path",
        "source_hunks",
        "target_score",
        "expression_score",
        "target_virtual_facts",
        "expression_virtual_facts",
        "stack_frame_facts",
        "stack_clean_no_anchor_evidence",
    ):
        value = next(
            (
                source.get(key)
                for source in sources
                if isinstance(source, Mapping) and source.get(key) is not None
            ),
            None,
        )
        if value is not None:
            evidence[key] = value
    return evidence


def _retained_draw_helper_boundary_ranked_candidates(
    terminal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    proof = terminal.get("source_model_proof")
    synthesis = proof.get("source_family_synthesis") if isinstance(proof, Mapping) else None
    sources = [
        terminal.get("ranked_retained_candidates"),
        terminal.get("retained_scored_probes"),
        proof.get("ranked_retained_candidates") if isinstance(proof, Mapping) else None,
        proof.get("retained_scored_probes") if isinstance(proof, Mapping) else None,
        proof.get("candidate_scores") if isinstance(proof, Mapping) else None,
        synthesis.get("ranked_retained_candidates") if isinstance(synthesis, Mapping) else None,
        synthesis.get("retained_scored_probes") if isinstance(synthesis, Mapping) else None,
        synthesis.get("candidate_scores") if isinstance(synthesis, Mapping) else None,
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, Sequence) or isinstance(source, (str, bytes)):
            continue
        for row in source:
            if not isinstance(row, Mapping):
                continue
            candidate = {
                key: row[key]
                for key in (
                    "candidate_id",
                    "dimension_id",
                    "source_retained",
                    "pcdump_path",
                    "source_hunks",
                    "target_score",
                    "expression_score",
                    "target_matched",
                    "target_targeted",
                    "target_virtual_distance",
                    "expression_matched",
                    "expression_targeted",
                    "expression_virtual_distance",
                    "stack_frame_facts",
                    "target_virtual_facts",
                    "expression_virtual_facts",
                    "terminal_blockers",
                    "blockers",
                )
                if row.get(key) is not None
            }
            key = _json_key(candidate) if candidate else str(row)
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
    return out


def _retained_candidate_has_source_evidence(row: Mapping[str, Any]) -> bool:
    return bool(
        _non_empty_str(row.get("pcdump_path"))
        and (
            _non_empty_str(row.get("source_retained"))
            or row.get("source_hunks")
        )
    )


def _retained_draw_helper_boundary_handoff_lane(
    terminal: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any] | None:
    function = _non_empty_str(terminal.get("function"))
    if function != _DRAW_FUNCTION:
        return None
    target_score = evidence.get("target_score")
    final_force = (
        _frontier_force_for_matching(terminal)
        or _force_phys_from_target_score(target_score)
        or _retained_stack_clean_force_from_virtual_facts(
            evidence.get("target_virtual_facts")
        )
    )
    if not final_force:
        return None
    frontier_id = _frontier_id(
        function,
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        ("dimension", _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION),
        ("force", final_force),
    )
    source_retained = _non_empty_str(evidence.get("source_retained"))
    pcdump_path = _non_empty_str(evidence.get("pcdump_path"))
    command = [
        "melee-agent",
        "debug",
        "suggest",
        "inlines",
        "--function",
        function,
    ]
    if source_retained:
        command.extend(["--source-file", source_retained])
    if pcdump_path:
        command.extend(["--pcdump", pcdump_path])
    command.extend(["--verify", "--json"])
    continuation = {
        "route": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "dimension_id": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "next_unsupported_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "command": shlex.join(command),
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "next_unsupported_source_model": (
            evidence.get("next_unsupported_source_model")
            or _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL
        ),
        "ranked_retained_candidates": list(
            evidence.get("ranked_retained_candidates") or []
        ),
    }
    for key in (
        "source_retained",
        "pcdump_path",
        "source_hunks",
        "target_score",
        "expression_score",
        "target_virtual_facts",
        "expression_virtual_facts",
        "stack_frame_facts",
    ):
        if evidence.get(key) is not None:
            continuation[key] = evidence[key]
    proof = dict(terminal.get("source_model_proof") or {})
    proof["next_unsupported_source_dimension"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    proof["next_unsupported_source_family"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
    )
    proof["next_unsupported_source_model"] = (
        continuation["next_unsupported_source_model"]
    )
    proof["unsupported_source_expression_class"] = (
        _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
    )
    lane: dict[str, Any] = {
        "rank": None,
        "frontier_id": frontier_id,
        "function": function,
        "family_id": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        "suppression_family": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        "kind": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_KIND,
        "status": "source-actionable",
        "terminal": False,
        "terminal_reason": None,
        "closed_by": [],
        "suppressed_by_terminal": False,
        "actionable": True,
        "attempted_targets": dict(final_force),
        "protected_targets": {},
        "final_force_phys": dict(final_force),
        "target_hits": _retained_stack_clean_virtual_hits(
            evidence.get("target_virtual_facts")
        ),
        "protected_hits": {},
        "match_percent": terminal.get("match_percent"),
        "normalized_drift": {
            **{key: None for key in _DRIFT_KEYS},
            "virtual_distance": (
                target_score.get("virtual_distance")
                if isinstance(target_score, Mapping)
                else None
            ),
        },
        "metrics": {
            "ranked_candidate_count": len(
                evidence.get("ranked_retained_candidates") or []
            ),
        },
        "best_candidate": None,
        "continuation": continuation,
        "dimension_id": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "source_model_layer_dimension_id": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "next_unsupported_source_model": continuation[
            "next_unsupported_source_model"
        ],
        "ranked_retained_candidates": list(
            evidence.get("ranked_retained_candidates") or []
        ),
        "source_model_proof": proof,
        "_mtime": terminal.get("_mtime") or 0.0,
        "_final_force_phys": dict(final_force),
    }
    for key in (
        "source_retained",
        "pcdump_path",
        "source_hunks",
        "target_score",
        "expression_score",
        "target_virtual_facts",
        "expression_virtual_facts",
        "stack_frame_facts",
    ):
        if evidence.get(key) is not None:
            lane[key] = evidence[key]
    for key in ("artifact", "summary_path", "source_file", "pcdump"):
        if terminal.get(key) is not None:
            lane[key] = terminal[key]
    return lane


def _retained_stack_clean_no_anchor_evidence(
    terminal: Mapping[str, Any],
) -> dict[str, Any] | None:
    for source in _retained_stack_clean_no_anchor_sources(terminal):
        evidence = source.get("stack_clean_no_anchor_evidence")
        if isinstance(evidence, Mapping):
            return dict(evidence)
    return None


def _retained_stack_clean_no_anchor_sources(
    row: Mapping[str, Any],
    *,
    include_aggregate_sources: bool = False,
) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    seen: set[int] = set()

    def add(raw: Any) -> None:
        if not isinstance(raw, Mapping):
            return
        identity = id(raw)
        if identity in seen:
            return
        seen.add(identity)
        sources.append(raw)

    add(row)
    add(row.get("terminal_summary"))
    score_classification = row.get("score_classification")
    if isinstance(score_classification, Mapping):
        add(score_classification.get("terminal_summary"))
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        add(proof)
        add(proof.get("source_family_synthesis"))
        add(proof.get("terminal_summary"))
    if include_aggregate_sources:
        for key in ("terminal_groups", "representative_frontiers"):
            values = row.get(key)
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                continue
            for value in values:
                add(value)
                if isinstance(value, Mapping):
                    representatives = value.get("representative_frontiers")
                    if (
                        isinstance(representatives, Sequence)
                        and not isinstance(representatives, (str, bytes))
                    ):
                        for representative in representatives:
                            add(representative)
    return sources


def _retained_stack_clean_no_anchor_terminal_completed(
    terminals: Sequence[Mapping[str, Any]],
) -> bool:
    return any(
        _frontier_closes_stack_clean_no_anchor_recovery(terminal)
        for terminal in terminals
    )


def _frontier_closes_stack_clean_no_anchor_recovery(
    row: Mapping[str, Any],
) -> bool:
    if any(
        _retained_stack_clean_no_anchor_source_completed(source)
        for source in _retained_stack_clean_no_anchor_sources(
            row,
            include_aggregate_sources=True,
        )
    ):
        return True
    closed = row.get("closed_families")
    if isinstance(closed, Sequence) and not isinstance(closed, (str, bytes)):
        return any(
            item in {
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY,
            }
            for item in closed
        )
    return False


def _stack_clean_no_anchor_seed_id(row: Mapping[str, Any]) -> str | None:
    for source in _retained_stack_clean_no_anchor_sources(
        row,
        include_aggregate_sources=True,
    ):
        evidence = source.get("stack_clean_no_anchor_evidence")
        if isinstance(evidence, Mapping):
            seed = _non_empty_str(
                evidence.get("seed_candidate_id")
                or evidence.get("candidate_id")
            )
            if seed is not None:
                return seed
        for key in (
            "suppressed_candidate_id",
            "seed_candidate_id",
            "candidate_id",
        ):
            seed = _non_empty_str(source.get(key))
            if seed is not None:
                return seed
    return None


def _stack_clean_no_anchor_lane_seed_id(row: Mapping[str, Any]) -> str | None:
    continuation = row.get("continuation")
    if isinstance(continuation, Mapping):
        for key in ("seed_candidate_id", "candidate_id"):
            seed = _non_empty_str(continuation.get(key))
            if seed is not None:
                return seed
    return _stack_clean_no_anchor_seed_id(row)


def _stack_clean_no_anchor_terminal_matches_lane(
    terminal: Mapping[str, Any],
    lane: Mapping[str, Any],
) -> bool:
    if terminal.get("function") != lane.get("function"):
        return False
    if not _retained_meta_stack_clean_no_anchor_recovery_lane(lane):
        return False
    if not _frontier_closes_stack_clean_no_anchor_recovery(terminal):
        return False

    terminal_seed = _stack_clean_no_anchor_seed_id(terminal)
    lane_seed = _stack_clean_no_anchor_lane_seed_id(lane)
    if terminal_seed and lane_seed and terminal_seed != lane_seed:
        return False

    terminal_force = _frontier_force_for_matching(terminal)
    lane_force = _frontier_force_for_matching(lane)
    if terminal_force and lane_force and terminal_force != lane_force:
        return False

    return True


def _retained_stack_clean_no_anchor_source_completed(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    for key in (
        "terminal_reason",
        "terminal_blocker",
        "reason",
        "next_unsupported_source_model",
        "next_unsupported_source_family",
        "next_unsupported_source_dimension",
    ):
        value = _non_empty_str(raw.get(key))
        if value in {
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY,
        }:
            return True
    for key in ("exhausted_source_dimension", "suppressed_frontier_dimension"):
        if (
            _non_empty_str(raw.get(key))
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ):
            return True
    attempted = raw.get("attempted_equivalence_classes")
    if (
        isinstance(attempted, Sequence)
        and not isinstance(attempted, (str, bytes))
        and _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION in attempted
        and raw.get("status") in {"synthesis-exhausted", "terminal", "complete"}
    ):
        return True
    exhausted = raw.get("exhausted_dimensions")
    if isinstance(exhausted, Sequence) and not isinstance(exhausted, (str, bytes)):
        for row in exhausted:
            if isinstance(row, Mapping):
                dimension = row.get("dimension_id")
                reason = row.get("exhaustion_reason") or row.get("reason")
            else:
                dimension = row
                reason = None
            if dimension == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION:
                return True
            if reason == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON:
                return True
    blockers = raw.get("terminal_blockers")
    if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes)):
        for blocker in blockers:
            if isinstance(blocker, Mapping):
                value = (
                    blocker.get("reason")
                    or blocker.get("terminal_blocker")
                    or blocker.get("blocker")
                )
            else:
                value = blocker
            if value in {
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
            }:
                return True
    return False


def _merge_stack_clean_terminal_summary_fields_for_row(
    row: dict[str, Any],
) -> None:
    summaries: list[Mapping[str, Any]] = []
    for summary in (
        row.get("terminal_summary"),
        _nested_value(row, ("score_classification", "terminal_summary")),
    ):
        if isinstance(summary, Mapping):
            summaries.append(summary)
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        proof_summary = proof.get("terminal_summary")
        if isinstance(proof_summary, Mapping):
            summaries.append(proof_summary)
    if not any(
        _retained_stack_clean_no_anchor_source_completed(summary)
        for summary in summaries
    ):
        return
    proof_out = dict(proof) if isinstance(proof, Mapping) else {}
    for summary in summaries:
        _merge_stack_clean_terminal_summary_fields(proof_out, summary)
    row["source_model_proof"] = proof_out


def _merge_stack_clean_terminal_summary_fields(
    source_model_proof: dict[str, Any],
    summary: Mapping[str, Any],
) -> None:
    if not _retained_stack_clean_no_anchor_source_completed(summary):
        return
    proof_already_completed = _retained_stack_clean_no_anchor_source_completed(
        source_model_proof
    )
    for key in _STACK_CLEAN_TERMINAL_SUMMARY_FIELDS:
        value = summary.get(key)
        if value is None:
            continue
        if not proof_already_completed or source_model_proof.get(key) is None:
            source_model_proof[key] = value

    synthesis = source_model_proof.get("source_family_synthesis")
    if not isinstance(synthesis, Mapping):
        return
    synthesis_out = dict(synthesis)
    synthesis_already_completed = _retained_stack_clean_no_anchor_source_completed(
        synthesis_out
    )
    for key in _STACK_CLEAN_TERMINAL_SUMMARY_FIELDS:
        value = summary.get(key)
        if value is None:
            continue
        if not synthesis_already_completed or synthesis_out.get(key) is None:
            synthesis_out[key] = value
    source_model_proof["source_family_synthesis"] = synthesis_out


def _retained_stack_clean_no_anchor_lane(
    terminal: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any] | None:
    function = _non_empty_str(terminal.get("function"))
    seed_candidate_id = _non_empty_str(evidence.get("seed_candidate_id"))
    source_retained = _non_empty_str(evidence.get("source_retained"))
    pcdump_path = _non_empty_str(evidence.get("pcdump_path"))
    source_hunks = evidence.get("source_hunks")
    if not function or not seed_candidate_id:
        return None
    if not source_retained or not pcdump_path:
        return None
    if not isinstance(source_hunks, list) or not source_hunks:
        return None

    target_score = evidence.get("target_score")
    expression_score = evidence.get("expression_score")
    final_force = (
        _frontier_force_for_matching(terminal)
        or _force_phys_from_target_score(target_score)
    )
    if not final_force:
        final_force = _retained_stack_clean_force_from_virtual_facts(
            evidence.get("target_virtual_facts")
        )
    attempted = dict(final_force)
    stack_frame_facts = (
        dict(evidence.get("stack_frame_facts"))
        if isinstance(evidence.get("stack_frame_facts"), Mapping)
        else {}
    )
    frontier_id = _frontier_id(
        function,
        _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        ("dimension", _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION),
        ("seed", seed_candidate_id),
        ("force", final_force),
    )
    continuation = {
        "route": _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "dimension_id": _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "next_unsupported_source_dimension": (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "candidate_id": seed_candidate_id,
        "seed_candidate_id": seed_candidate_id,
        "source_retained": source_retained,
        "pcdump_path": pcdump_path,
        "source_hunks": list(source_hunks),
        "target_score": target_score,
        "expression_score": expression_score,
        "stack_frame_facts": stack_frame_facts,
        "target_virtual_facts": list(evidence.get("target_virtual_facts") or []),
        "expression_virtual_facts": list(
            evidence.get("expression_virtual_facts") or []
        ),
        "ranked_recovery_probes": list(
            evidence.get("ranked_recovery_probes") or []
        ),
    }
    proof = dict(terminal.get("source_model_proof") or {})
    proof["next_unsupported_source_dimension"] = (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    proof["next_unsupported_source_model"] = _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_MODEL
    proof["next_unsupported_source_family"] = (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    proof["stack_clean_no_anchor_evidence"] = dict(evidence)
    lane: dict[str, Any] = {
        "rank": None,
        "frontier_id": frontier_id,
        "function": function,
        "family_id": _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        "suppression_family": _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "terminal": False,
        "terminal_reason": None,
        "closed_by": [],
        "suppressed_by_terminal": False,
        "actionable": True,
        "attempted_targets": attempted,
        "protected_targets": {},
        "final_force_phys": dict(final_force),
        "target_hits": _retained_stack_clean_virtual_hits(
            evidence.get("target_virtual_facts")
        ),
        "protected_hits": {},
        "match_percent": terminal.get("match_percent"),
        "normalized_drift": {
            **{key: None for key in _DRIFT_KEYS},
            "normalized_diff_lines": stack_frame_facts.get(
                "normalized_diff_lines"
            ),
            "virtual_distance": (
                target_score.get("virtual_distance")
                if isinstance(target_score, Mapping)
                else None
            ),
        },
        "metrics": {
            "candidate_count": 1,
            "stack_frame_delta": stack_frame_facts.get("frame_delta"),
            "normalized_diff_lines": stack_frame_facts.get(
                "normalized_diff_lines"
            ),
            "opcode_similarity": stack_frame_facts.get("opcode_similarity"),
        },
        "best_candidate": None,
        "continuation": continuation,
        "candidate_id": seed_candidate_id,
        "dimension_id": _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "source_model_layer_dimension_id": (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "source_retained": source_retained,
        "pcdump_path": pcdump_path,
        "source_hunks": list(source_hunks),
        "target_score": target_score,
        "expression_score": expression_score,
        "stack_frame_facts": stack_frame_facts,
        "target_virtual_facts": list(evidence.get("target_virtual_facts") or []),
        "expression_virtual_facts": list(
            evidence.get("expression_virtual_facts") or []
        ),
        "stack_clean_no_anchor_evidence": dict(evidence),
        "source_model_proof": proof,
        "_mtime": terminal.get("_mtime") or 0.0,
        "_final_force_phys": dict(final_force),
    }
    for key in ("artifact", "summary_path", "source_file", "pcdump"):
        if terminal.get(key) is not None:
            lane[key] = terminal[key]
    return lane


def _retained_stack_clean_force_from_virtual_facts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return {}
    out: dict[str, int] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        virtual = _to_int(row.get("virtual"))
        expected = _register_num(row.get("expected"))
        if virtual is None or expected is None:
            continue
        out[str(virtual)] = expected
    return dict(sorted(out.items(), key=lambda item: _int_sort_key(item[0])))


def _retained_stack_clean_virtual_hits(raw: Any) -> dict[str, bool]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return {}
    hits: dict[str, bool] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        virtual = _to_int(row.get("virtual"))
        if virtual is None:
            continue
        hits[str(virtual)] = bool(row.get("matched"))
    return hits


def _retained_terminal_semantic_recombine_blocks(
    proof: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    paths = (
        (
            "source_family_synthesis",
            "post_ceiling_source_family_discovery",
            "semantic_recombine",
        ),
        ("source_family_synthesis", "semantic_recombine"),
        ("semantic_recombine",),
    )
    out: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for path in paths:
        semantic = _nested_value(proof, path)
        if not isinstance(semantic, Mapping):
            continue
        identity = id(semantic)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(semantic)
    return out


def _retained_semantic_recombine_actionable_candidates(
    semantic: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    if semantic.get("status") != "actionable":
        return []
    candidates = semantic.get("ranked_candidates")
    if not isinstance(candidates, list):
        return []
    accepted: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("dimension_id") != _SORT_SEMANTIC_RECOMBINE_DIMENSION:
            continue
        if candidate.get("status") in {"terminal", "blocked"}:
            continue
        if not (
            candidate.get("accepted") is True
            or candidate.get("recommendation") == "continue"
        ):
            continue
        if candidate.get("blockers") or candidate.get("terminal_blockers"):
            continue
        source_hunks = candidate.get("source_hunks")
        if not isinstance(source_hunks, list) or not source_hunks:
            continue
        if not _retained_sort_semantic_recombine_has_scored_source_proof(
            candidate
        ):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=_retained_semantic_recombine_candidate_rank_key)


def _retained_sort_semantic_recombine_has_scored_source_proof(
    candidate: Mapping[str, Any],
) -> bool:
    source_retained = _non_empty_str(candidate.get("source_retained"))
    if source_retained is None:
        return False
    source_hunks = candidate.get("source_hunks")
    if not isinstance(source_hunks, list) or not source_hunks:
        return False
    score = candidate.get("target_score")
    if not isinstance(score, Mapping) or score.get("estimated") is True:
        return False
    structural = candidate.get("structural_guard")
    if not isinstance(structural, Mapping) or structural.get("estimated") is True:
        return False
    return bool(
        candidate.get("structural_guard_accepted") is True
        or structural.get("accepted") is True
        or structural.get("status") == "accepted"
    )


def _retained_semantic_recombine_candidate_rank_key(
    candidate: Mapping[str, Any],
) -> tuple[Any, ...]:
    score = _retained_semantic_recombine_candidate_score(candidate)
    matched = _to_int(score.get("matched"))
    if matched is None:
        matched = _to_int(candidate.get("target_matched"))
    virtual_distance = _to_int(score.get("virtual_distance"))
    if virtual_distance is None:
        virtual_distance = _to_int(candidate.get("target_virtual_distance"))
    return (
        -(matched if matched is not None else -1),
        virtual_distance if virtual_distance is not None else math.inf,
        str(candidate.get("candidate_id") or ""),
    )


def _retained_semantic_recombine_candidate_score(
    candidate: Mapping[str, Any],
) -> Mapping[str, Any]:
    for key in ("target_score", "target_score_estimate"):
        score = candidate.get(key)
        if isinstance(score, Mapping):
            return score
    return {}


def _retained_semantic_recombine_candidate_lane(
    terminal: Mapping[str, Any],
    _semantic: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    function = _non_empty_str(terminal.get("function"))
    candidate_id = _non_empty_str(candidate.get("candidate_id"))
    source_hunks = candidate.get("source_hunks")
    if not function or not candidate_id:
        return None
    if not isinstance(source_hunks, list) or not source_hunks:
        return None

    attempted = _normalized_int_mapping(terminal.get("attempted_targets"))
    protected = _normalized_int_mapping(terminal.get("protected_targets"))
    final_force = _frontier_force_for_matching(terminal)
    if not final_force:
        final_force = dict(sorted(
            {**protected, **attempted}.items(),
            key=lambda item: _int_sort_key(item[0]),
        ))
    frontier_id = _frontier_id(
        function,
        _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY,
        ("force", final_force),
        ("candidate", candidate_id),
    )
    score = _retained_semantic_recombine_candidate_score(candidate)
    metrics = _retained_semantic_recombine_metrics(candidate, score)
    hits = _retained_semantic_recombine_virtual_hits(score)
    continuation: dict[str, Any] = {
        "route": _SORT_SEMANTIC_RECOMBINE_DIMENSION,
        "candidate_id": candidate_id,
        "source_hunks": list(source_hunks),
    }
    parents = candidate.get("parents")
    if parents is None:
        parents = _nested_value(candidate, ("source_route", "parents"))
    if parents is not None:
        continuation["parents"] = parents
    for key in (
        "source_components",
        "target_score",
        "target_score_estimate",
        "source_retained",
        "pcdump_path",
        "structural_guard",
        "structural_guard_accepted",
        "real_score_authority",
    ):
        if candidate.get(key) is not None:
            continuation[key] = candidate[key]

    lane: dict[str, Any] = {
        "rank": None,
        "frontier_id": frontier_id,
        "function": function,
        "family_id": _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY,
        "suppression_family": (
            _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY
        ),
        "kind": _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_KIND,
        "status": "actionable",
        "terminal": False,
        "terminal_reason": None,
        "closed_by": [],
        "suppressed_by_terminal": False,
        "actionable": True,
        "attempted_targets": dict(attempted),
        "protected_targets": dict(protected),
        "final_force_phys": dict(final_force),
        "target_hits": dict(hits),
        "protected_hits": dict(hits),
        "match_percent": terminal.get("match_percent"),
        "normalized_drift": {key: None for key in _DRIFT_KEYS},
        "metrics": metrics,
        "best_candidate": None,
        "continuation": continuation,
        "source_hunks": list(source_hunks),
        "_mtime": terminal.get("_mtime") or 0.0,
        "_final_force_phys": dict(final_force),
    }
    for key in (
        "source_components",
        "target_score",
        "source_retained",
        "pcdump_path",
        "structural_guard",
        "structural_guard_accepted",
        "real_score_authority",
    ):
        if candidate.get(key) is not None:
            lane[key] = candidate[key]
    for key in ("artifact", "summary_path", "source_file", "pcdump", "pcdump_path"):
        if terminal.get(key) is not None:
            lane[key] = terminal[key]
    return lane


def _retained_semantic_recombine_metrics(
    candidate: Mapping[str, Any],
    score: Mapping[str, Any],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric_key, candidate_key in (
        ("matched", "target_matched"),
        ("targeted", "target_targeted"),
        ("virtual_distance", "target_virtual_distance"),
    ):
        value = score.get(metric_key)
        if value is None:
            value = candidate.get(candidate_key)
        if value is not None:
            metrics[metric_key] = value
    return metrics


def _retained_semantic_recombine_virtual_hits(
    score: Mapping[str, Any],
) -> dict[str, bool]:
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}
    hits: dict[str, bool] = {}
    for key, row in virtuals.items():
        if isinstance(row, Mapping) and isinstance(row.get("matched"), bool):
            hits[str(key)] = row["matched"]
        elif isinstance(row, bool):
            hits[str(key)] = row
    return hits


def _retained_meta_lane_actionable(row: Mapping[str, Any]) -> bool:
    continuation = row.get("continuation")
    has_source_edits = _retained_meta_continuation_has_source_edits(continuation)
    if row.get("actionable") is False:
        return has_source_edits
    if _retained_meta_continuation_has_action(continuation):
        return True
    if row.get("source_hunk") or row.get("source_hunks"):
        return True
    if row.get("command"):
        return True
    return False


def _retained_meta_continuation_source_hunks(raw: Any) -> list[Any]:
    if not isinstance(raw, Mapping):
        return []
    out: list[Any] = []
    source_hunk = raw.get("source_hunk")
    if source_hunk is not None:
        out.append(source_hunk)
    source_hunks = raw.get("source_hunks")
    if isinstance(source_hunks, list):
        out.extend(row for row in source_hunks if row is not None)
    return out


def _retained_meta_continuation_has_source_edits(raw: Any) -> bool:
    return bool(_retained_meta_continuation_source_hunks(raw))


def _retained_meta_continuation_has_action(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    return bool(
        _non_empty_str(raw.get("command"))
        or _non_empty_str(raw.get("source_retained"))
        or _retained_meta_continuation_has_source_edits(raw)
    )


def _retained_meta_public_lane(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items()
        if not str(key).startswith("_")
    }


def _retained_meta_lane_rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    rank = _to_int(row.get("rank"))
    continuation = row.get("continuation")
    stage_rank = _retained_meta_lane_source_model_stage(row)
    route_quality = 4
    if isinstance(continuation, Mapping):
        if continuation.get("command"):
            route_quality = 0
        elif _retained_meta_continuation_has_source_edits(continuation):
            route_quality = 1
    elif row.get("source_hunk") or row.get("source_hunks"):
        route_quality = 2
    elif row.get("command"):
        route_quality = 3
    return (
        -stage_rank,
        rank if rank is not None and rank > 0 else 10**9,
        route_quality,
        str(row.get("frontier_id") or ""),
    )


def _retained_meta_lane_source_model_stage(row: Mapping[str, Any]) -> int:
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        return _source_model_proof_priority(proof)[0]
    pseudo = _retained_meta_source_model_stage_pseudo_proof(row)
    if not pseudo:
        return 0
    return _source_model_proof_priority(pseudo)[0]


def _retained_meta_terminal_source_model_stage(row: Mapping[str, Any]) -> int:
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        return _source_model_proof_priority(proof)[0]
    return _retained_meta_lane_source_model_stage(row)


def _retained_meta_source_model_stage_pseudo_proof(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    exhausted: list[str] = []
    for key in (
        "dimension_id",
        "source_model_layer_dimension_id",
        "exhausted_source_dimension",
    ):
        value = _non_empty_str(row.get(key))
        if value is not None:
            exhausted.append(value)
    if isinstance(row.get("exhausted_dimensions"), list):
        for raw in row["exhausted_dimensions"]:
            if isinstance(raw, Mapping):
                value = _non_empty_str(raw.get("dimension_id"))
            else:
                value = _non_empty_str(raw)
            if value is not None:
                exhausted.append(value)
    candidate_dimension = _dimension_from_candidate_id(
        _non_empty_str(row.get("candidate_id"))
    )
    if candidate_dimension is not None:
        exhausted.append(candidate_dimension)
    if exhausted:
        out["exhausted_dimensions"] = _dedupe_strings(exhausted)
    for key in (
        "next_unsupported_source_dimension",
        "next_unsupported_source_family",
        "next_unsupported_source_model",
    ):
        value = _non_empty_str(row.get(key))
        if value is not None:
            out[key] = value
    continuation = row.get("continuation")
    if isinstance(continuation, Mapping):
        route = _non_empty_str(continuation.get("route"))
        if route is not None:
            out.setdefault("next_unsupported_source_dimension", route)
        for key in (
            "dimension_id",
            "source_model_layer_dimension_id",
            "next_unsupported_source_dimension",
            "next_unsupported_source_family",
            "next_unsupported_source_model",
        ):
            value = _non_empty_str(continuation.get(key))
            if value is None:
                continue
            if key in {"dimension_id", "source_model_layer_dimension_id"}:
                current = out.get("exhausted_dimensions")
                if not isinstance(current, list):
                    current = []
                out["exhausted_dimensions"] = _dedupe_strings([*current, value])
            else:
                out[key] = value
    return out


def _retained_meta_suppression_signature(
    row: Mapping[str, Any],
) -> tuple[str, str] | None:
    family = (
        _non_empty_str(row.get("suppression_family"))
        or _non_empty_str(row.get("family_id"))
    )
    force = _frontier_force_for_matching(row)
    if not family or not force:
        return None
    return family, _json_key(force)


def _retained_meta_terminal_groups(
    terminals: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for terminal in terminals:
        key = _retained_meta_terminal_group_key(terminal)
        group = groups.setdefault(
            key,
            {
                "family_id": key[0],
                "terminal_reason": key[1],
                "suppression_family": key[2],
                "count": 0,
                "suppressed_count": 0,
                "attempted_targets": {},
                "protected_targets": {},
                "final_force_phys": {},
                "closed_by_sample": [],
                "representative_frontiers": [],
                "allocator_facts": [],
                "source_spans": [],
                "exhausted_dimensions": [],
                "next_unsupported_source_model": None,
                "next_unsupported_source_family": None,
                "unsupported_source_expression_class": None,
                "evidence_priority": 0,
                "direct_terminal_count": 0,
                "max_terminal_mtime": 0.0,
                "_terminal_selection_key": (0, 0, 0.0, (0, 0, 0, 0), 0.0, 0),
            },
        )
        group["count"] += 1
        proof = terminal.get("source_model_proof")
        if isinstance(proof, Mapping):
            selection_key = _retained_terminal_proof_selection_key(terminal, proof)
            group["_terminal_selection_key"] = max(
                group["_terminal_selection_key"],
                selection_key,
            )
        stack_clean_proof = _retained_meta_stack_clean_final_proof_from_terminal(
            terminal
        )
        if stack_clean_proof is not None:
            if not _retained_post_stack_clean_no_anchor_source_shape_completed(
                stack_clean_proof
            ):
                stack_clean_proof["_retained_synthetic_stack_clean_final"] = True
            group["_terminal_selection_key"] = max(
                group["_terminal_selection_key"],
                _retained_terminal_proof_selection_key(terminal, stack_clean_proof),
            )
        directness = _retained_terminal_proof_directness(terminal)
        if directness >= 2:
            group["direct_terminal_count"] += 1
        group["max_terminal_mtime"] = max(
            float(group.get("max_terminal_mtime") or 0.0),
            _retained_terminal_proof_mtime(terminal),
        )
        if terminal.get("suppressed_by_terminal"):
            group["suppressed_count"] += 1
        _retained_meta_merge_targets(
            group["attempted_targets"],
            terminal.get("attempted_targets"),
        )
        _retained_meta_merge_targets(
            group["protected_targets"],
            terminal.get("protected_targets"),
        )
        _retained_meta_merge_targets(
            group["final_force_phys"],
            terminal.get("final_force_phys"),
        )
        if not group["final_force_phys"]:
            _retained_meta_merge_targets(
                group["final_force_phys"],
                terminal.get("_final_force_phys"),
            )
        for artifact in terminal.get("closed_by") or []:
            if artifact and artifact not in group["closed_by_sample"]:
                group["closed_by_sample"].append(str(artifact))
        for metric, value in _retained_meta_metrics(terminal).items():
            if value is not None:
                group[metric] = value
        group["representative_frontiers"].append(
            _retained_meta_representative_frontier(terminal)
        )
        group["allocator_facts"] = _dedupe_dicts([
            *group["allocator_facts"],
            *_retained_meta_allocator_facts(terminal),
        ])
        group["source_spans"] = _dedupe_dicts([
            *group["source_spans"],
            *_retained_meta_source_spans(terminal),
        ])
        for dimension in _retained_meta_exhausted_dimensions(terminal):
            if dimension not in group["exhausted_dimensions"]:
                group["exhausted_dimensions"].append(dimension)
        next_model = _retained_meta_next_unsupported_source_model(terminal)
        next_priority = _source_model_proof_priority(
            terminal.get("source_model_proof")
            if isinstance(terminal.get("source_model_proof"), Mapping)
            else {}
        )
        if next_model and (
            not group.get("next_unsupported_source_model")
            or next_priority > group.get("_next_unsupported_priority", (0, 0, 0))
        ):
            group["next_unsupported_source_model"] = next_model
            group["_next_unsupported_priority"] = next_priority
        next_family = _retained_meta_next_unsupported_source_family(terminal)
        if next_family and (
            not group.get("next_unsupported_source_family")
            or next_priority > group.get("_next_unsupported_family_priority", (0, 0, 0))
        ):
            group["next_unsupported_source_family"] = next_family
            group["_next_unsupported_family_priority"] = next_priority
        if _frontier_closes_draw_protected_expression_reconcile(terminal):
            group["terminal_reason"] = (
                _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
            )
            group["terminal_blocker"] = (
                _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
            )
            group["terminal_blockers"] = _dedupe_strings(
                [
                    *_string_items(group.get("terminal_blockers")),
                    *_string_items(terminal.get("terminal_blockers")),
                    _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON,
                ]
            )
            group["next_unsupported_source_model"] = (
                _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
            )
            group["next_unsupported_source_family"] = (
                _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
            )
            if _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE not in {
                row.get("dimension_id") if isinstance(row, Mapping) else row
                for row in group["exhausted_dimensions"]
            }:
                group["exhausted_dimensions"].append(
                    {
                        "dimension_id": (
                            _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE
                        ),
                        "status": "scored-terminal",
                        "exhaustion_reason": (
                            _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
                        ),
                    }
                )
        if _retained_post_stack_loop_callsite_source_context_completed(terminal):
            group["next_unsupported_source_model"] = (
                _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
            )
            group["next_unsupported_source_family"] = (
                _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
            )
            if _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION not in {
                row.get("dimension_id") if isinstance(row, Mapping) else row
                for row in group["exhausted_dimensions"]
            }:
                group["exhausted_dimensions"].append(
                    {
                        "dimension_id": (
                            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
                        ),
                        "status": "scored-terminal",
                        "exhaustion_reason": (
                            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
                        ),
                    }
                )
        elif _retained_post_stack_clean_no_anchor_source_shape_completed(terminal):
            group["next_unsupported_source_model"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
            )
            group["next_unsupported_source_family"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
            )
            if _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION not in {
                row.get("dimension_id") if isinstance(row, Mapping) else row
                for row in group["exhausted_dimensions"]
            }:
                group["exhausted_dimensions"].append(
                    {
                        "dimension_id": (
                            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
                        ),
                        "status": "scored-terminal",
                        "exhaustion_reason": (
                            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
                        ),
                    }
                )
        elif _retained_stack_clean_no_anchor_final_source_completed(terminal):
            normalized_next_model = (
                _non_empty_str(stack_clean_proof.get("next_unsupported_source_model"))
                if isinstance(stack_clean_proof, Mapping)
                else None
            )
            normalized_next_family = (
                _non_empty_str(stack_clean_proof.get("next_unsupported_source_family"))
                if isinstance(stack_clean_proof, Mapping)
                else None
            )
            group["next_unsupported_source_model"] = (
                normalized_next_model
                or _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
            )
            group["next_unsupported_source_family"] = (
                normalized_next_family
                or _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
            )
            if _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION not in {
                row.get("dimension_id") if isinstance(row, Mapping) else row
                for row in group["exhausted_dimensions"]
            }:
                group["exhausted_dimensions"].append(
                    {
                        "dimension_id": (
                            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
                        ),
                        "status": "scored-terminal",
                        "exhaustion_reason": (
                            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
                        ),
                    }
                )
        unsupported = _retained_meta_unsupported_source_expression_class(terminal)
        if unsupported and not group.get("unsupported_source_expression_class"):
            group["unsupported_source_expression_class"] = unsupported
        group["evidence_priority"] = max(
            int(group.get("evidence_priority") or 0),
            _retained_meta_terminal_evidence_priority(terminal),
        )

    out = []
    for group in groups.values():
        group["closed_by_sample"] = group["closed_by_sample"][:3]
        group["representative_frontiers"] = group["representative_frontiers"][:3]
        group.pop("_next_unsupported_priority", None)
        group.pop("_next_unsupported_family_priority", None)
        group["_terminal_selection_key"] = tuple(group["_terminal_selection_key"])
        out.append(group)
    return sorted(
        out,
        key=_retained_meta_terminal_group_priority,
    )


def _retained_meta_terminal_group_priority(
    group: Mapping[str, Any],
) -> tuple[Any, ...]:
    post_stack_loop_callsite = (
        group.get("terminal_reason")
        == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
        or group.get("next_unsupported_source_family")
        == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
        or group.get("next_unsupported_source_family")
        == _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
        or group.get("next_unsupported_source_model")
        == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
        or group.get("next_unsupported_source_model")
        == _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
        or any(
            (
                row.get("dimension_id") if isinstance(row, Mapping) else row
            )
            == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            for row in group.get("exhausted_dimensions") or []
        )
    )
    post_stack_clean = (
        group.get("terminal_reason")
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
        or group.get("next_unsupported_source_family")
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
        or group.get("next_unsupported_source_model")
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
        or any(
            (
                row.get("dimension_id") if isinstance(row, Mapping) else row
            )
            == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
            for row in group.get("exhausted_dimensions") or []
        )
    )
    final_stack_clean = (
        group.get("terminal_reason")
        == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
        or group.get("next_unsupported_source_family")
        == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        or group.get("next_unsupported_source_model")
        == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        or any(
            (
                row.get("dimension_id") if isinstance(row, Mapping) else row
            )
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            for row in group.get("exhausted_dimensions") or []
        )
    )
    selection_key = group.get("_terminal_selection_key")
    if not isinstance(selection_key, tuple):
        selection_key = (0, 0, 0.0, (0, 0, 0, 0), 0.0, 0)
    semantic = selection_key[3] if len(selection_key) > 3 else (0, 0, 0, 0)
    if not isinstance(semantic, tuple):
        semantic = (0, 0, 0, 0)
    return (
        -int(selection_key[0] if len(selection_key) > 0 else 0),
        -int(selection_key[1] if len(selection_key) > 1 else 0),
        -float(selection_key[2] if len(selection_key) > 2 else 0.0),
        tuple(-int(value) for value in semantic),
        (
            0
            if post_stack_loop_callsite
            else 1
            if post_stack_clean
            else 2
            if final_stack_clean
            else 3
        ),
        -int(group.get("count") or 0),
        str(group.get("family_id") or ""),
        str(group.get("terminal_reason") or ""),
    )


def _retained_meta_terminal_group_key(
    terminal: Mapping[str, Any],
) -> tuple[str, str, str]:
    family = _non_empty_str(terminal.get("family_id")) or "unknown-family"
    reason = _non_empty_str(terminal.get("terminal_reason")) or "terminal"
    suppression = (
        _non_empty_str(terminal.get("suppression_family"))
        or family
        or "terminal"
    )
    return family, reason, suppression


def _retained_meta_merge_targets(target: dict[str, int], value: Any) -> None:
    for key, raw in _normalized_int_mapping(value).items():
        target.setdefault(str(key), raw)


def _retained_meta_metrics(terminal: Mapping[str, Any]) -> dict[str, Any]:
    metrics = terminal.get("metrics")
    out = {
        key: terminal.get(key)
        for key in (
            "candidate_count",
            "scored_count",
            "matched",
            "targeted",
            "best_expression_matched",
            "best_expression_targeted",
            "best_target_matched",
            "best_target_targeted",
            "exact_count",
        )
        if terminal.get(key) is not None
    }
    if isinstance(metrics, Mapping):
        for key in (
            "candidate_count",
            "scored_count",
            "matched",
            "targeted",
            "best_expression_matched",
            "best_expression_targeted",
            "best_target_matched",
            "best_target_targeted",
            "exact_count",
        ):
            if key in metrics and key not in out:
                out[key] = metrics[key]
    return out


def _retained_meta_representative_frontier(
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    out = {
        "frontier_id": terminal.get("frontier_id"),
        "artifact": terminal.get("artifact"),
        "family_id": terminal.get("family_id"),
        "terminal_reason": terminal.get("terminal_reason"),
    }
    metrics = _retained_meta_metrics(terminal)
    if metrics:
        out["metrics"] = metrics
    closed_by = [
        str(item) for item in (terminal.get("closed_by") or [])
        if item
    ][:3]
    if closed_by:
        out["closed_by_sample"] = closed_by
    return out


def _retained_meta_allocator_facts(
    terminal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        for key in (
            "target_anchors",
            "expression_anchors",
            "residual_blocker_targets",
        ):
            rows = proof.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, Mapping):
                        fact = _retained_meta_allocator_fact(row)
                        if fact is not None:
                            facts.append(fact)
        for row in proof.get("candidate_scores") or []:
            if not isinstance(row, Mapping):
                continue
            for key in ("wrong_registers", "expression_wrong_registers"):
                for wrong in row.get(key) or []:
                    if isinstance(wrong, Mapping):
                        fact = _retained_meta_allocator_fact(wrong)
                        if fact is not None:
                            facts.append(fact)
            for score_key in ("target_score", "expression_score"):
                score = row.get(score_key)
                if isinstance(score, Mapping):
                    virtuals = score.get("virtuals")
                    if isinstance(virtuals, Mapping):
                        for virtual, virtual_row in virtuals.items():
                            if isinstance(virtual_row, Mapping):
                                fact = _retained_meta_allocator_fact(
                                    {"virtual": virtual, **virtual_row}
                                )
                                if fact is not None:
                                    facts.append(fact)
    for key in ("attempted_targets", "protected_targets", "final_force_phys"):
        for virtual, expected in _normalized_int_mapping(terminal.get(key)).items():
            if any(
                _to_int(fact.get("virtual")) == int(virtual)
                and _register_num(fact.get("expected")) == expected
                and _register_num(fact.get("actual")) is not None
                for fact in facts
            ):
                continue
            facts.append({"virtual": int(virtual), "expected": expected, "actual": None})
    return _dedupe_allocator_facts(facts)


def _dedupe_allocator_facts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped = _dedupe_dicts(rows)
    concrete_keys = {
        (_to_int(row.get("virtual")), _register_num(row.get("expected")))
        for row in deduped
        if _register_num(row.get("actual")) is not None
    }
    return [
        row for row in deduped
        if _register_num(row.get("actual")) is not None
        or (_to_int(row.get("virtual")), _register_num(row.get("expected")))
        not in concrete_keys
    ]


def _retained_meta_allocator_fact(row: Mapping[str, Any]) -> dict[str, Any] | None:
    virtual = _to_int(_first_present(row, "virtual", "baseline_virtual"))
    expected = _register_num(_first_present(row, "expected", "target_reg"))
    actual = _register_num(_first_present(row, "actual", "assigned_reg"))
    if virtual is None or expected is None:
        return None
    out: dict[str, Any] = {
        "virtual": virtual,
        "expected": expected,
        "actual": actual,
    }
    name = _non_empty_str(row.get("name"))
    if name:
        out["name"] = name
    return out


def _retained_meta_source_spans(
    terminal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        for key in ("source_spans", "next_unsupported_source_spans"):
            for row in proof.get(key) or []:
                if isinstance(row, Mapping):
                    spans.append(dict(row))
        for row in proof.get("expression_anchors") or []:
            if isinstance(row, Mapping):
                _retained_meta_append_source_span(spans, row.get("baseline_source"))
        for row in proof.get("candidate_scores") or []:
            if not isinstance(row, Mapping):
                continue
            for wrong in row.get("expression_wrong_registers") or []:
                if isinstance(wrong, Mapping):
                    _retained_meta_append_source_span(spans, wrong.get("baseline_source"))
            for hunk in row.get("source_hunks") or []:
                _retained_meta_append_source_hunk(spans, hunk)
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            for row in synthesis.get("source_hunks_by_candidate") or []:
                if not isinstance(row, Mapping):
                    continue
                for hunk in row.get("source_hunks") or []:
                    _retained_meta_append_source_hunk(spans, hunk)
            for row in synthesis.get("retained_scored_probes") or []:
                if not isinstance(row, Mapping):
                    continue
                for hunk in row.get("source_hunks") or []:
                    _retained_meta_append_source_hunk(spans, hunk)
    for blocker in terminal.get("route_terminal_blockers") or []:
        if isinstance(blocker, Mapping):
            source_file = _non_empty_str(blocker.get("source_file"))
            if source_file:
                spans.append({"source_file": source_file, "confidence": "route-blocker"})
    source_file = _non_empty_str(terminal.get("source_file"))
    if source_file:
        spans.append({"source_file": source_file, "confidence": "frontier-source-file"})
    return _dedupe_dicts(spans)


def _retained_meta_append_source_span(spans: list[dict[str, Any]], value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    source_file = _non_empty_str(value.get("source_file"))
    if not source_file:
        return
    span: dict[str, Any] = {"source_file": source_file}
    source_line = _to_int(value.get("source_line"))
    if source_line is not None:
        span["source_line"] = source_line
    source_col = _to_int(value.get("source_col"))
    if source_col is not None:
        span["source_col"] = source_col
    for key in ("name", "expression", "confidence", "kind"):
        text = _non_empty_str(value.get(key))
        if text:
            span[key] = text
    spans.append(span)


def _retained_meta_append_source_hunk(spans: list[dict[str, Any]], value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    line = _to_int(value.get("old_start") or value.get("new_start"))
    span: dict[str, Any] = {"confidence": "source-hunk"}
    if line is not None:
        span["source_line"] = line
    hunk_id = _non_empty_str(value.get("hunk_id"))
    if hunk_id:
        span["hunk_id"] = hunk_id
    if len(span) > 1:
        spans.append(span)


def _retained_meta_exhausted_dimensions(
    terminal: Mapping[str, Any],
) -> list[str]:
    values: list[str] = []
    for row in terminal.get("exhausted_dimensions") or []:
        if isinstance(row, Mapping):
            dimension = _non_empty_str(row.get("dimension_id"))
        else:
            dimension = _non_empty_str(row)
        if dimension and dimension not in values:
            values.append(dimension)
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        for item in _string_items(proof.get("exhausted_source_dimension")):
            if item not in values:
                values.append(item)
        for item in _string_items(proof.get("exhausted_dimensions")):
            if item not in values:
                values.append(item)
        for row in proof.get("exhausted_dimensions") or []:
            if not isinstance(row, Mapping):
                continue
            dimension = _non_empty_str(row.get("dimension_id"))
            if dimension and dimension not in values:
                values.append(dimension)
    synthesis = (
        proof.get("source_family_synthesis")
        if isinstance(proof, Mapping)
        else None
    )
    if isinstance(synthesis, Mapping):
        for item in _string_items(synthesis.get("exhausted_source_dimension")):
            if item not in values:
                values.append(item)
        for item in _string_items(synthesis.get("exhausted_dimensions")):
            if item not in values:
                values.append(item)
        for row in synthesis.get("exhausted_dimensions") or []:
            if isinstance(row, Mapping):
                dimension = _non_empty_str(row.get("dimension_id"))
                if dimension and dimension not in values:
                    values.append(dimension)
    return values


def _retained_meta_next_unsupported_source_model(
    terminal: Mapping[str, Any],
) -> str | None:
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        value = _non_empty_str(proof.get("next_unsupported_source_model"))
        if value:
            return value
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            return _non_empty_str(synthesis.get("next_unsupported_source_model"))
    return None


def _retained_meta_next_unsupported_source_family(
    terminal: Mapping[str, Any],
) -> str | None:
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        value = _non_empty_str(proof.get("next_unsupported_source_family"))
        if value:
            return value
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            return _non_empty_str(synthesis.get("next_unsupported_source_family"))
    return None


def _retained_meta_unsupported_source_expression_class(
    terminal: Mapping[str, Any],
) -> str | None:
    value = _non_empty_str(terminal.get("unsupported_source_expression_class"))
    if value:
        return value
    function = _non_empty_str(terminal.get("function"))
    proof = terminal.get("source_model_proof")
    if isinstance(proof, Mapping):
        value = _non_empty_str(proof.get("unsupported_source_expression_class"))
        if value:
            return value
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            value = _non_empty_str(
                synthesis.get("unsupported_source_expression_class")
            )
            if value:
                return value
        if function == _DRAW_FUNCTION and _is_draw_coupled_expression_anchor_cluster(
            proof.get("expression_anchors"),
        ):
            return _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
    return None


def _is_draw_coupled_expression_anchor_cluster(raw: Any) -> bool:
    if not isinstance(raw, list):
        return False
    anchors = [row for row in raw if isinstance(row, Mapping)]
    virtuals = {
        _to_int(row.get("virtual"))
        for row in anchors
        if _to_int(row.get("virtual")) is not None
    }
    if {32, 37, 46} <= virtuals:
        return True
    text = " ".join(
        str(row.get(key) or "")
        for row in anchors
        for key in ("name", "expression", "source_kind")
    )
    return (
        "col_offset" in text
        and "row_offset" in text
        and ("fsubs" in text or "fpr-temp" in text)
    )


def _retained_meta_terminal_proof(
    terminals: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    allocator_facts = _dedupe_dicts([
        fact
        for terminal in terminals
        for fact in _retained_meta_allocator_facts(terminal)
    ])
    source_spans = _dedupe_dicts([
        span
        for terminal in terminals
        for span in _retained_meta_source_spans(terminal)
    ])
    next_model = _retained_meta_ranked_next_unsupported_source_model(groups)
    unsupported = next(
        (
            group.get("unsupported_source_expression_class")
            for group in groups
            if group.get("unsupported_source_expression_class")
        ),
        None,
    )
    best_source_model_proof = _retained_meta_preferred_source_model_proof(terminals)
    proof = {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "unmapped_source_spans": source_spans,
        "source_spans": source_spans,
        "allocator_facts": allocator_facts,
        "next_unsupported_source_model": next_model,
        **(
            {"unsupported_source_expression_class": unsupported}
            if unsupported
            else {}
        ),
    }
    if best_source_model_proof:
        for key in (
            "kind",
            "source_family_synthesis",
            "attempted_equivalence_classes",
            "candidate_scores",
            "retained_scored_probes",
            "source_hunks_by_candidate",
            "terminal_reason",
            "exhausted_source_dimension",
            "exhausted_dimensions",
            "next_unsupported_source_dimension",
            "next_unsupported_source_model",
            "next_unsupported_source_family",
            "next_unsupported_source_spans",
            "stack_clean_no_anchor_evidence",
            "post_stack_clean_no_anchor_evidence",
            "stack_frame_facts",
            "source_hunks",
            "source_retained",
            "pcdump_path",
            "unsupported_source_expression_model",
            "unsupported_source_expression_class",
            "target_score",
            "expression_score",
            "terminal_blocker",
            "terminal_blockers",
            "post_row_offset_owner_expression_lifetime_evidence",
            "current_ceiling_selection",
        ):
            value = best_source_model_proof.get(key)
            if (
                value is None
                and key in {"retained_scored_probes", "source_hunks_by_candidate"}
            ):
                synthesis = best_source_model_proof.get("source_family_synthesis")
                if isinstance(synthesis, Mapping):
                    value = synthesis.get(key)
            if value is None and key == "terminal_blocker":
                synthesis = best_source_model_proof.get("source_family_synthesis")
                if isinstance(synthesis, Mapping):
                    value = synthesis.get("terminal_blocker")
            if value is not None:
                proof[key] = value
        if _retained_stack_clean_no_anchor_final_source_completed(
            best_source_model_proof
        ) and not _retained_post_stack_clean_no_anchor_source_shape_completed(
            best_source_model_proof
        ):
            _normalize_stack_clean_final_terminal_proof(proof)
        elif _retained_post_row_offset_owner_expression_lifetime_completed(proof):
            _normalize_post_row_offset_owner_expression_lifetime_terminal_proof(proof)
        elif _retained_post_stack_loop_callsite_source_context_completed(proof):
            proof["terminal_reason"] = (
                _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
            )
            proof["terminal_blocker"] = (
                _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
            )
            _normalize_post_stack_loop_callsite_terminal_proof(proof)
        elif _retained_post_stack_clean_no_anchor_source_shape_completed(proof):
            proof["terminal_reason"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
            )
            proof["terminal_blocker"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER
            )
    _retained_meta_backfill_draw_protected_expression_reconcile_family(proof, groups)
    _retained_meta_backfill_draw_helper_boundary_final_family(proof)
    _retained_meta_backfill_sort_cross_tu_no_modeled_family(proof)
    _retained_meta_merge_same_family_retained_scores(proof, terminals)
    recombine = _retained_meta_recombine_negative_evidence(terminals)
    if recombine:
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            synthesis = dict(synthesis)
        else:
            synthesis = {}
        synthesis.setdefault("recombine_negative_evidence", recombine)
        proof["source_family_synthesis"] = synthesis
    return proof


def _retained_meta_backfill_draw_protected_expression_reconcile_family(
    proof: dict[str, Any],
    groups: Sequence[Mapping[str, Any]],
) -> None:
    if not any(
        group.get("suppression_family")
        == _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE
        for group in groups
    ):
        return
    proof["next_unsupported_source_model"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
    )
    proof["next_unsupported_source_family"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    proof["terminal_reason"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    )
    proof["terminal_blocker"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    )
    blockers = _dedupe_strings(
        [
            *_string_items(proof.get("terminal_blockers")),
            _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON,
        ]
    )
    proof["terminal_blockers"] = blockers
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
    else:
        synthesis_out = {}
    synthesis_out["next_unsupported_source_model"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
    )
    synthesis_out["next_unsupported_source_family"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    synthesis_out["terminal_reason"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    )
    synthesis_out["terminal_blockers"] = _dedupe_strings(
        [
            *_string_items(synthesis_out.get("terminal_blockers")),
            *blockers,
        ]
    )
    raw_exhausted = synthesis_out.get("exhausted_dimensions")
    exhausted = [
        dict(row)
        for row in (raw_exhausted if isinstance(raw_exhausted, list) else [])
        if isinstance(row, Mapping)
    ]
    exhausted.append({
        "dimension_id": _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        "status": "scored-terminal",
        "exhaustion_reason": (
            _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
        ),
    })
    synthesis_out["exhausted_dimensions"] = _dedupe_dicts(exhausted)
    proof["source_family_synthesis"] = synthesis_out


def _retained_meta_backfill_draw_helper_boundary_final_family(
    proof: dict[str, Any],
) -> None:
    if not _retained_draw_helper_boundary_completed(proof):
        return
    _normalize_draw_helper_boundary_terminal_proof(proof)


def _retained_draw_helper_boundary_completed(proof: Mapping[str, Any]) -> bool:
    if _source_model_proof_string(proof, "kind") == (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_KIND
    ):
        return True
    if (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        not in _source_model_proof_dimension_ids(proof)
        and _source_model_proof_string(proof, "next_unsupported_source_family")
        != _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
    ):
        return False
    reasons = {
        _source_model_proof_string(proof, "terminal_reason"),
        _source_model_proof_string(proof, "terminal_blocker"),
    }
    reasons.update(_nested_strings_for_key(proof, "reason"))
    reasons.update(_nested_strings_for_key(proof, "terminal_blocker"))
    return any(
        reason in _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASONS
        for reason in reasons
        if reason is not None
    )


def _normalize_draw_helper_boundary_terminal_proof(proof: dict[str, Any]) -> None:
    proof["next_unsupported_source_family"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
    )
    proof["next_unsupported_source_model"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
    )
    proof.pop("next_unsupported_source_dimension", None)
    proof["exhausted_source_dimension"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    exhausted = list(proof.get("exhausted_dimensions") or [])
    if _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION not in {
        row.get("dimension_id") if isinstance(row, Mapping) else row
        for row in exhausted
    }:
        exhausted.append(
            {
                "dimension_id": (
                    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
                ),
                "status": "scored-terminal",
                "exhaustion_reason": proof.get("terminal_reason")
                or _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
            }
        )
    proof["exhausted_dimensions"] = exhausted
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
    else:
        synthesis_out = {}
    synthesis_out["next_unsupported_source_family"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
    )
    synthesis_out["next_unsupported_source_model"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
    )
    synthesis_out.pop("next_unsupported_source_dimension", None)
    synthesis_out["exhausted_source_dimension"] = (
        _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    synthesis_exhausted = list(synthesis_out.get("exhausted_dimensions") or [])
    if _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION not in {
        row.get("dimension_id") if isinstance(row, Mapping) else row
        for row in synthesis_exhausted
    }:
        synthesis_exhausted.append(exhausted[-1])
    synthesis_out["exhausted_dimensions"] = synthesis_exhausted
    proof["source_family_synthesis"] = synthesis_out


def _retained_meta_backfill_sort_cross_tu_no_modeled_family(
    proof: dict[str, Any],
) -> None:
    if (
        _source_model_proof_string(proof, "next_unsupported_source_model")
        != _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
    ):
        return
    if _source_model_proof_string(proof, "next_unsupported_source_family") is None:
        proof["next_unsupported_source_family"] = (
            _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
        )
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
    else:
        synthesis_out = {}
    synthesis_out.setdefault(
        "next_unsupported_source_model",
        _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL,
    )
    synthesis_out.setdefault(
        "next_unsupported_source_family",
        _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY,
    )
    blockers = _dedupe_strings(
        [
            *_string_items(proof.get("terminal_blockers")),
            *_string_items(synthesis_out.get("terminal_blockers")),
            _SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER,
        ]
    )
    if blockers:
        proof["terminal_blockers"] = blockers
        synthesis_out["terminal_blockers"] = blockers
    proof["source_family_synthesis"] = synthesis_out


def _retained_meta_merge_same_family_retained_scores(
    proof: dict[str, Any],
    terminals: Sequence[Mapping[str, Any]],
) -> None:
    if _source_model_proof_retained_score_count(proof):
        return
    selected_family = _source_model_proof_string(
        proof,
        "next_unsupported_source_family",
    )
    if selected_family is None:
        return
    ranked: list[tuple[int, list[Any], Any]] = []
    for terminal in terminals:
        terminal_proof = terminal.get("source_model_proof")
        if not isinstance(terminal_proof, Mapping):
            continue
        terminal_family = _source_model_proof_string(
            terminal_proof,
            "next_unsupported_source_family",
        )
        if terminal_family != selected_family:
            continue
        for source in (
            terminal_proof,
            terminal_proof.get("source_family_synthesis"),
        ):
            if not isinstance(source, Mapping):
                continue
            retained = source.get("retained_scored_probes")
            if isinstance(retained, list) and retained:
                ranked.append((
                    len(retained),
                    retained,
                    source.get("source_hunks_by_candidate"),
                ))
    if not ranked:
        return
    _count, retained, source_hunks = max(ranked, key=lambda row: row[0])
    proof["retained_scored_probes"] = retained
    if source_hunks is not None and not proof.get("source_hunks_by_candidate"):
        proof["source_hunks_by_candidate"] = source_hunks
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        synthesis = dict(synthesis)
    else:
        synthesis = {}
    synthesis["retained_scored_probes"] = retained
    if source_hunks is not None and not synthesis.get("source_hunks_by_candidate"):
        synthesis["source_hunks_by_candidate"] = source_hunks
    proof["source_family_synthesis"] = synthesis


def _retained_meta_recombine_negative_evidence(
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    for terminal in terminals:
        proof = terminal.get("source_model_proof")
        if not isinstance(proof, Mapping):
            continue
        synthesis = proof.get("source_family_synthesis")
        if not isinstance(synthesis, Mapping):
            continue
        evidence = synthesis.get("recombine_negative_evidence")
        if isinstance(evidence, Mapping):
            return dict(evidence)
    return None


def _retained_meta_best_source_model_proof(
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    ranked: list[tuple[tuple[int, int, int, int], int, dict[str, Any]]] = []
    for index, terminal in enumerate(terminals):
        proof = terminal.get("source_model_proof")
        if not isinstance(proof, Mapping):
            continue
        ranked.append((_source_model_proof_priority(proof), index, dict(proof)))
    if not ranked:
        return None
    return _source_model_proof_without_stale_blockers(
        max(ranked, key=lambda row: (row[0], row[1]))[2]
    )


def _retained_meta_preferred_source_model_proof(
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    ranked: list[tuple[tuple[Any, ...], int, dict[str, Any]]] = []
    for index, terminal in enumerate(terminals):
        proof = terminal.get("source_model_proof")
        if isinstance(proof, Mapping):
            candidate = dict(proof)
            for key in (
                "artifact",
                "summary_path",
                "terminal_reason",
                "terminal_blocker",
            ):
                if terminal.get(key) is not None and candidate.get(key) is None:
                    candidate[key] = terminal[key]
            ranked.append((
                _retained_terminal_proof_selection_key(terminal, candidate),
                index,
                candidate,
            ))
        stack_clean_proof = _retained_meta_stack_clean_final_proof_from_terminal(
            terminal
        )
        if stack_clean_proof is not None:
            for key in (
                "artifact",
                "summary_path",
                "terminal_reason",
                "terminal_blocker",
            ):
                if terminal.get(key) is not None and stack_clean_proof.get(key) is None:
                    stack_clean_proof[key] = terminal[key]
            if not _retained_post_stack_clean_no_anchor_source_shape_completed(
                stack_clean_proof
            ):
                stack_clean_proof["_retained_synthetic_stack_clean_final"] = True
            stack_clean_priority = _retained_terminal_proof_selection_key(
                terminal,
                stack_clean_proof,
            )
            ranked.append((
                stack_clean_priority,
                index,
                stack_clean_proof,
            ))
    if not ranked:
        return None
    selection_key, _index, selected = max(ranked, key=lambda row: (row[0], row[1]))
    proof = _source_model_proof_without_stale_blockers(selected)
    proof["current_ceiling_selection"] = _retained_terminal_proof_selection_summary(
        proof,
        selection_key,
    )
    if (
        _retained_stack_clean_no_anchor_final_source_completed(proof)
        and not _retained_post_stack_clean_no_anchor_source_shape_completed(proof)
    ):
        _normalize_stack_clean_final_terminal_proof(proof)
    elif _retained_post_row_offset_owner_expression_lifetime_completed(proof):
        _normalize_post_row_offset_owner_expression_lifetime_terminal_proof(proof)
    elif _retained_post_stack_loop_callsite_source_context_completed(proof):
        _normalize_post_stack_loop_callsite_terminal_proof(proof)
    return proof


def _retained_terminal_proof_selection_key(
    terminal: Mapping[str, Any],
    proof: Mapping[str, Any],
) -> tuple[Any, ...]:
    directness = _retained_terminal_proof_directness(terminal)
    currentness = _retained_terminal_proof_currentness_class(proof)
    mtime = _retained_terminal_proof_mtime(terminal)
    semantic = _source_model_proof_priority(proof)
    stack_chain = _retained_terminal_proof_draw_stack_terminal_chain(proof)
    sort_stage = _sort_direct_source_model_proof_stage_rank(proof) or 0
    post_cross_sort_stage = sort_stage if sort_stage >= 12 else 0
    if _retained_post_row_offset_owner_expression_lifetime_completed(proof):
        directness = max(directness, 6)
    elif _retained_post_stack_loop_callsite_source_context_completed(proof):
        directness = max(directness, 5)
    elif _retained_post_stack_clean_no_anchor_source_shape_completed(proof):
        directness = max(directness, 4)
    if proof.get("_retained_synthetic_stack_clean_final") is True:
        semantic = (
            max(semantic[0], 13),
            semantic[1],
            semantic[2],
            semantic[3],
        )
    if not stack_chain:
        return (
            post_cross_sort_stage,
            int(mtime),
            currentness,
            directness,
            semantic,
            0.0,
            _source_model_proof_evidence_score(proof),
        )
    return (
        directness,
        currentness,
        mtime,
        semantic,
        0.0,
        _source_model_proof_evidence_score(proof),
    )


def _retained_terminal_proof_directness(terminal: Mapping[str, Any]) -> int:
    summary_path = _non_empty_str(terminal.get("summary_path")) or ""
    path_parts = {
        part.strip("[]")
        for part in summary_path.replace("[", ".[").split(".")
        if part
    }
    if path_parts & {"context", "current_ceiling", "meta_ceiling", "terminal_proof"}:
        return 0
    if not summary_path:
        return 3
    if "terminal_frontiers" in path_parts:
        return 2
    if terminal.get("terminal") and isinstance(
        terminal.get("source_model_proof"),
        Mapping,
    ):
        return 2
    return 1


def _retained_terminal_proof_mtime(terminal: Mapping[str, Any]) -> float:
    raw_mtime = terminal.get("_mtime")
    if isinstance(raw_mtime, (int, float)) and not isinstance(raw_mtime, bool):
        return float(raw_mtime)
    artifact = _non_empty_str(terminal.get("artifact"))
    if artifact is None:
        return 0.0
    try:
        return float(Path(artifact).stat().st_mtime)
    except OSError:
        return 0.0


def _retained_terminal_proof_currentness_class(proof: Mapping[str, Any]) -> int:
    if _retained_post_row_offset_owner_expression_lifetime_completed(proof):
        return 16
    if _retained_post_stack_loop_callsite_source_context_completed(proof):
        return 15
    if _retained_post_stack_clean_no_anchor_source_shape_completed(proof):
        return 13
    if _retained_stack_clean_no_anchor_final_source_completed(proof):
        return 13
    return _source_model_proof_priority(proof)[0]


def _retained_terminal_proof_draw_stack_terminal_chain(
    proof: Mapping[str, Any],
) -> bool:
    return (
        _retained_post_row_offset_owner_expression_lifetime_completed(proof)
        or _retained_stack_clean_no_anchor_final_source_completed(proof)
        or _retained_post_stack_clean_no_anchor_source_shape_completed(proof)
        or _retained_post_stack_loop_callsite_source_context_completed(proof)
    )


def _retained_terminal_proof_selection_summary(
    proof: Mapping[str, Any],
    selection_key: tuple[Any, ...],
) -> dict[str, Any]:
    return {
        "selected_family": _source_model_proof_string(
            proof,
            "next_unsupported_source_family",
        ),
        "selected_terminal_reason": _non_empty_str(proof.get("terminal_reason")),
        "selected_artifact": _non_empty_str(proof.get("artifact")),
        "selected_summary_path": _non_empty_str(proof.get("summary_path")),
        "selected_mtime": _retained_terminal_proof_mtime(proof),
        "selection_reason": "mtime/currentness/semantic-priority",
    }


def _retained_meta_stack_clean_final_source_model_proof(
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    ranked: list[tuple[tuple[int, int, int, int], int, dict[str, Any]]] = []
    for index, terminal in enumerate(terminals):
        if not _frontier_closes_stack_clean_no_anchor_recovery(terminal):
            continue
        proof = _retained_meta_stack_clean_final_proof_from_terminal(terminal)
        if proof is None:
            continue
        ranked.append((_source_model_proof_priority(proof), index, proof))
    if not ranked:
        return None
    proof = _source_model_proof_without_stale_blockers(
        max(ranked, key=lambda row: (row[0], row[1]))[2]
    )
    _normalize_stack_clean_final_terminal_proof(proof)
    return proof


def _retained_meta_stack_clean_final_proof_from_terminal(
    terminal: Mapping[str, Any],
) -> dict[str, Any] | None:
    sources = _retained_stack_clean_no_anchor_sources(
        terminal,
        include_aggregate_sources=True,
    )
    proof = terminal.get("source_model_proof")
    if (
        isinstance(proof, Mapping)
        and _retained_stack_clean_no_anchor_final_source_completed(proof)
    ):
        out = dict(proof)
    else:
        out = {}
    for source in sources:
        if not _retained_stack_clean_no_anchor_final_source_completed(source):
            continue
        for key in _STACK_CLEAN_TERMINAL_SUMMARY_FIELDS:
            value = source.get(key)
            if value is not None and out.get(key) is None:
                out[key] = value
        for key in (
            "candidate_scores",
            "retained_scored_probes",
            "terminal_blockers",
            "stack_clean_no_anchor_evidence",
            "post_stack_clean_no_anchor_evidence",
            "exhausted_dimensions",
            "exhausted_source_dimension",
            "terminal_reason",
            "terminal_blocker",
            "next_unsupported_source_family",
            "next_unsupported_source_model",
            "source_hunks_by_candidate",
        ):
            value = source.get(key)
            if value is not None and out.get(key) is None:
                out[key] = value
    if not _retained_stack_clean_no_anchor_final_source_completed(out):
        return None
    _normalize_stack_clean_final_terminal_proof(out)
    return out


def _normalize_stack_clean_final_terminal_proof(proof: dict[str, Any]) -> None:
    if _retained_post_stack_clean_no_anchor_source_shape_completed(proof):
        return
    synthesis = proof.get("source_family_synthesis")
    evidence = proof.get("stack_clean_no_anchor_evidence")
    if not isinstance(evidence, Mapping) and isinstance(synthesis, Mapping):
        evidence = synthesis.get("stack_clean_no_anchor_evidence")
    has_seed_evidence = isinstance(evidence, Mapping) and bool(evidence)
    if has_seed_evidence:
        proof["next_unsupported_source_model"] = (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
        )
        proof["next_unsupported_source_family"] = (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        )
        proof["next_unsupported_source_dimension"] = (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        )
        proof["stack_clean_no_anchor_evidence"] = dict(evidence)
    else:
        proof["next_unsupported_source_model"] = (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        )
        proof["next_unsupported_source_family"] = (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        )
        if (
            proof.get("next_unsupported_source_dimension")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ):
            proof.pop("next_unsupported_source_dimension", None)
    proof["exhausted_source_dimension"] = (
        _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    proof["terminal_reason"] = _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    proof["terminal_blocker"] = _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER
    exhausted = list(proof.get("exhausted_dimensions") or [])
    if _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION not in {
        row.get("dimension_id") if isinstance(row, Mapping) else row
        for row in exhausted
    }:
        exhausted.append(
            {
                "dimension_id": _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
                "status": "scored-terminal",
                "exhaustion_reason": (
                    _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
                ),
            }
        )
    proof["exhausted_dimensions"] = exhausted
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
        if has_seed_evidence:
            synthesis_out["next_unsupported_source_model"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
            )
            synthesis_out["next_unsupported_source_family"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
            )
            synthesis_out["next_unsupported_source_dimension"] = (
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
            )
            synthesis_out["stack_clean_no_anchor_evidence"] = dict(evidence)
        else:
            synthesis_out["next_unsupported_source_model"] = (
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
            )
            synthesis_out["next_unsupported_source_family"] = (
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
            )
            if (
                synthesis_out.get("next_unsupported_source_dimension")
                == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ):
                synthesis_out.pop("next_unsupported_source_dimension", None)
        synthesis_out["exhausted_source_dimension"] = (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        )
        synthesis_out["terminal_reason"] = (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
        )
        synthesis_out["terminal_blocker"] = (
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER
        )
        synthesis_exhausted = list(synthesis_out.get("exhausted_dimensions") or [])
        if _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION not in {
            row.get("dimension_id") if isinstance(row, Mapping) else row
            for row in synthesis_exhausted
        }:
            synthesis_exhausted.append(exhausted[-1])
        synthesis_out["exhausted_dimensions"] = synthesis_exhausted
        proof["source_family_synthesis"] = synthesis_out


def _normalize_post_stack_loop_callsite_terminal_proof(proof: dict[str, Any]) -> None:
    proof["next_unsupported_source_family"] = (
        _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    proof["next_unsupported_source_model"] = (
        _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    proof["next_unsupported_source_dimension"] = None
    proof["terminal_reason"] = (
        _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    proof["terminal_blocker"] = (
        _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
    )
    exhausted = list(proof.get("exhausted_dimensions") or [])
    if _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION not in {
        row.get("dimension_id") if isinstance(row, Mapping) else row
        for row in exhausted
    }:
        exhausted.append(
            {
                "dimension_id": _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
                "status": "scored-terminal",
                "exhaustion_reason": (
                    _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
                ),
            }
        )
    proof["exhausted_source_dimension"] = (
        _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )
    proof["exhausted_dimensions"] = exhausted
    synthesis = proof.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
        synthesis_out["next_unsupported_source_family"] = (
            _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
        )
        synthesis_out["next_unsupported_source_model"] = (
            _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
        )
        synthesis_out["next_unsupported_source_dimension"] = None
        synthesis_out["terminal_reason"] = (
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
        )
        synthesis_out["terminal_blocker"] = (
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
        )
        synthesis_out["exhausted_source_dimension"] = (
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        )
        synthesis_exhausted = list(synthesis_out.get("exhausted_dimensions") or [])
        if _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION not in {
            row.get("dimension_id") if isinstance(row, Mapping) else row
            for row in synthesis_exhausted
        }:
            synthesis_exhausted.append(exhausted[-1])
        synthesis_out["exhausted_dimensions"] = synthesis_exhausted
        proof["source_family_synthesis"] = synthesis_out


def _retained_meta_rank(meta: Mapping[str, Any]) -> tuple[int, int, int, int]:
    status = str(meta.get("status") or "")
    stage_rank = 0
    evidence_rank = 0
    source_shape_rank = 1 if meta.get("source_shape_exhausted") is True else 0
    if status == "actionable":
        next_frontier = meta.get("next_frontier")
        if isinstance(next_frontier, Mapping):
            stage_rank = _retained_meta_lane_source_model_stage(next_frontier)
    else:
        proof = meta.get("terminal_proof")
        if isinstance(proof, Mapping):
            priority = _source_model_proof_priority(proof)
            stage_rank = priority[0]
            evidence_rank = priority[1]
            if (
                proof.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND
                and stage_rank == 0
            ):
                stage_rank = 8
    status_rank = 1 if status == "actionable" else 0
    if status == "not-present":
        return (-1, -1, 0, 0)
    return (stage_rank, status_rank, source_shape_rank, evidence_rank)


def _retained_meta_ranked_next_unsupported_source_model(
    groups: Sequence[Mapping[str, Any]],
) -> str | None:
    ranked: list[tuple[tuple[int, int, int, int, int, int], int, str]] = []
    for index, group in enumerate(groups):
        model = _non_empty_str(group.get("next_unsupported_source_model"))
        if not model:
            continue
        source_spans = group.get("source_spans")
        exhausted = group.get("exhausted_dimensions")
        facts = group.get("allocator_facts")
        ranked.append(
            (
                (
                    int(group.get("evidence_priority") or 0),
                    0 if "#981-era artifact" in model else 1,
                    1 if isinstance(source_spans, list) and source_spans else 0,
                    len(exhausted) if isinstance(exhausted, list) else 0,
                    len(facts) if isinstance(facts, list) else 0,
                    int(group.get("count") or 0),
                ),
                -index,
                model,
            )
        )
    if not ranked:
        return None
    return max(ranked, key=lambda row: (row[0], row[1]))[2]


def _retained_meta_terminal_evidence_priority(row: Mapping[str, Any]) -> int:
    proof = row.get("source_model_proof")
    proof_stage = (
        _source_model_proof_priority(proof)[0]
        if isinstance(proof, Mapping)
        else 0
    )
    if proof_stage >= 5:
        return 5
    if _frontier_concrete_protected_loss_terminal(row):
        return 3
    if proof_stage >= 4:
        return 4
    synthesis = (
        proof.get("source_family_synthesis")
        if isinstance(proof, Mapping)
        else None
    )
    if (
        isinstance(synthesis, Mapping)
        and synthesis.get("evidence_status")
        in {"artifact-synthesis-data", "artifact-score-rows"}
    ):
        return 2
    if row.get("family_id") == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY:
        return 1
    return 0


def _retained_meta_closed_families(
    terminals: Sequence[Mapping[str, Any]],
) -> list[str]:
    families = {
        str(row.get("family_id") or row.get("suppression_family"))
        for row in terminals
        if row.get("family_id") or row.get("suppression_family")
    }
    return sorted(families)


def _dedupe_dicts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = _json_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _extend_retained_meta_text(lines: list[str], value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    if value.get("status") != "terminal-current-source-shape-ceiling":
        return
    lines.append(f"  ceiling: {value.get('terminal_reason')}")
    groups = value.get("terminal_groups")
    if isinstance(groups, list) and groups:
        compact = []
        for group in groups[:4]:
            if not isinstance(group, Mapping):
                continue
            compact.append(
                f"{group.get('family_id')}/{group.get('terminal_reason')} "
                f"x{group.get('count')}"
            )
        if compact:
            lines.append("  groups: " + "; ".join(compact))
    proof = value.get("terminal_proof")
    if not isinstance(proof, Mapping):
        return
    next_model = _non_empty_str(proof.get("next_unsupported_source_model"))
    if next_model is not None:
        lines.append(f"  next unsupported source model: {next_model}")
    next_family = _non_empty_str(proof.get("next_unsupported_source_family"))
    if next_family is not None:
        lines.append(f"  next unsupported source family: {next_family}")
    next_spans = proof.get("next_unsupported_source_spans")
    if isinstance(next_spans, list) and next_spans:
        rendered_next_spans = [
            _render_retained_meta_next_source_span(span)
            for span in next_spans
            if isinstance(span, Mapping)
        ]
        rendered_next_spans = [item for item in rendered_next_spans if item]
        if rendered_next_spans:
            lines.append(
                "  next unsupported source spans: "
                + "; ".join(rendered_next_spans[:4])
            )
    facts = proof.get("allocator_facts")
    if isinstance(facts, list) and facts:
        rendered = [
            _render_retained_meta_allocator_fact(fact)
            for fact in facts
            if isinstance(fact, Mapping)
        ]
        rendered = [item for item in rendered if item]
        if rendered:
            lines.append("  allocator facts: " + "; ".join(rendered[:6]))
    spans = proof.get("source_spans")
    if isinstance(spans, list) and spans:
        rendered_spans = [
            _render_retained_meta_source_span(span)
            for span in spans
            if isinstance(span, Mapping)
        ]
        rendered_spans = [item for item in rendered_spans if item]
        if rendered_spans:
            lines.append("  source spans: " + "; ".join(rendered_spans[:6]))


def _render_retained_meta_next_source_span(span: Mapping[str, Any]) -> str | None:
    candidate_id = _non_empty_str(span.get("candidate_id"))
    dimension_id = _non_empty_str(span.get("dimension_id"))
    components = span.get("source_components")
    hunks = span.get("source_hunks")
    parts: list[str] = []
    if candidate_id is not None:
        parts.append(candidate_id)
    if dimension_id is not None:
        parts.append(f"dimension={dimension_id}")
    if isinstance(components, list) and components:
        component_ids = [
            _non_empty_str(row.get("component_id"))
            for row in components
            if isinstance(row, Mapping)
        ]
        component_ids = [item for item in component_ids if item is not None]
        if component_ids:
            parts.append("components=" + ",".join(component_ids[:4]))
    if isinstance(hunks, list) and hunks:
        parts.append(f"hunks={len(hunks)}")
    return " ".join(parts) if parts else None


def _render_retained_meta_allocator_fact(fact: Mapping[str, Any]) -> str | None:
    virtual = _to_int(fact.get("virtual"))
    expected = _register_num(fact.get("expected"))
    actual = _register_num(fact.get("actual"))
    if virtual is None or expected is None:
        return None
    text = f"ig{virtual} wants r{expected}"
    if actual is not None:
        text += f" got r{actual}"
    name = _non_empty_str(fact.get("name"))
    if name and name != f"ig{virtual}":
        text = f"{name} {text}"
    return text


def _render_retained_meta_source_span(span: Mapping[str, Any]) -> str | None:
    source_file = _non_empty_str(span.get("source_file"))
    line = _to_int(span.get("source_line"))
    name = _non_empty_str(span.get("name") or span.get("hunk_id"))
    if source_file:
        text = source_file
        if line is not None:
            text += f":{line}"
    elif line is not None:
        text = f"line {line}"
    else:
        return name
    if name:
        text += f" {name}"
    return text


def _resolve_path(path: Path | str, *, repo_root: Path) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = repo_root / resolved
    return resolved.resolve()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RetainedFrontierTriageError(
            f"could not read artifact {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RetainedFrontierTriageError(
            f"could not parse artifact {path}: {exc}"
        ) from exc


def _extract_frontiers(payload: Any, *, artifact: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, mapping, function, context in _walk_mappings(payload):
        frontier = _frontier_from_mapping(
            mapping,
            summary_path=".".join(path),
            function=function,
            artifact=artifact,
            context=context,
        )
        if frontier is not None:
            out.append(frontier)
    return out


def _extract_retained_simplify_exhaustions(
    payload: Any,
    *,
    artifact: Path,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, mapping, function, _context in _walk_mappings(payload):
        exhaustion = _retained_simplify_exhaustion_from_mapping(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=".".join(path),
        )
        if exhaustion is not None:
            out.append(exhaustion)
    return out


def _retained_simplify_exhaustion_from_mapping(
    mapping: Mapping[str, Any],
    *,
    function: str | None,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any] | None:
    if mapping.get("terminal_blocker") != (
        "no-retained-candidate-improved-residual-force-phys"
    ):
        return None
    if mapping.get("retained_mode") is not True:
        return None
    if not isinstance(function, str) or not function:
        function = _infer_function_from_mapping(mapping)
    if not isinstance(function, str) or not function:
        return None
    residual_force = _normalized_int_mapping(mapping.get("residual_force_phys"))
    if not residual_force:
        return None
    summary = mapping.get("summary")
    if not isinstance(summary, Mapping):
        return None
    compiled = _to_int(summary.get("compiled")) or 0
    if compiled <= 0:
        return None
    progress_hits = _to_int(summary.get("progress_hits"))
    if progress_hits != 0:
        return None
    source_file = _non_empty_str(
        mapping.get("source_file") or mapping.get("source_retained")
    )
    if source_file is None:
        return None
    ranked = mapping.get("ranked_probes")
    protected_force = _normalized_int_mapping(mapping.get("protected_force_phys"))
    return {
        "function": function,
        "artifact": str(artifact),
        "summary_path": summary_path,
        "terminal_blocker": mapping.get("terminal_blocker"),
        "source_file": source_file,
        "pcdump_path": _non_empty_str(
            mapping.get("pcdump_path") or mapping.get("pcdump")
        ),
        "retained_probe_count": len(ranked) if isinstance(ranked, list) else 0,
        "compiled": compiled,
        "skipped": _to_int(summary.get("skipped")) or 0,
        "compile_failures": _to_int(summary.get("compile_failures")) or 0,
        "gate_rejected": _to_int(summary.get("gate_rejected")) or 0,
        "progress_hits": progress_hits,
        "protected_force_phys": protected_force,
        "residual_force_phys": residual_force,
        "resume": (
            dict(mapping.get("resume"))
            if isinstance(mapping.get("resume"), Mapping)
            else None
        ),
    }


def _apply_retained_simplify_exhaustions(
    frontiers: list[dict[str, Any]],
    exhaustions: Sequence[Mapping[str, Any]],
) -> None:
    if not exhaustions:
        return
    for frontier in frontiers:
        continuation = frontier.get("continuation")
        if not isinstance(continuation, Mapping):
            continue
        if continuation.get("route") != "retained-common-subexpr-residual-handoff":
            continue
        residual_force = _normalized_int_mapping(
            continuation.get("residual_force_phys")
        )
        source_retained = _non_empty_str(continuation.get("source_retained"))
        pcdump_path = _non_empty_str(continuation.get("pcdump_path"))
        if not residual_force or source_retained is None:
            continue
        for exhaustion in exhaustions:
            if exhaustion.get("function") != frontier.get("function"):
                continue
            if _normalized_int_mapping(
                exhaustion.get("residual_force_phys")
            ) != residual_force:
                continue
            source_file = _non_empty_str(exhaustion.get("source_file"))
            if source_file is None or not _path_suffix_match(
                source_file,
                source_retained,
            ):
                continue
            exhaustion_pcdump = _non_empty_str(exhaustion.get("pcdump_path"))
            if (
                pcdump_path is not None
                and exhaustion_pcdump is not None
                and not _path_suffix_match(exhaustion_pcdump, pcdump_path)
            ):
                continue
            public_exhaustion = {
                key: value for key, value in exhaustion.items()
                if key not in {"function", "summary_path"}
            }
            frontier["residual_simplify_exhaustion"] = public_exhaustion
            updated = dict(continuation)
            updated["residual_simplify_exhaustion"] = public_exhaustion
            frontier["continuation"] = updated
            break


def _walk_mappings(
    value: Any,
    path: tuple[str, ...] = (),
    function: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> Iterable[tuple[tuple[str, ...], Mapping[str, Any], str | None, dict[str, Any]]]:
    if isinstance(value, Mapping):
        local_context = _frontier_context(value, context)
        local_function = value.get("function")
        if not isinstance(local_function, str) or not local_function:
            local_function = _infer_function_from_mapping(value)
        if not isinstance(local_function, str) or not local_function:
            local_function = function
        yield path, value, local_function, local_context
        for key, child in value.items():
            yield from _walk_mappings(
                child,
                path=path + (str(key),),
                function=local_function,
                context=local_context,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_mappings(
                child,
                path=path + (f"[{index}]",),
                function=function,
                context=context,
            )


def _frontier_context(
    mapping: Mapping[str, Any],
    inherited: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = dict(inherited or {})
    for key in (
        "class_id",
        "target_ig",
        "target_reg",
        "target_reg_num",
        "target_order",
        "target_orders",
        "force_phys",
        "force_phys_targets",
        "final_force_phys",
        "source_file",
        "source",
        "source_retained",
        "pcdump",
        "pcdump_path",
        "baseline_pcdump_path",
        "candidate_force_phys",
    ):
        if key in mapping and mapping[key] is not None:
            out[key] = mapping[key]
    evidence = mapping.get("evidence")
    if (
        isinstance(evidence, Mapping)
        and evidence.get("final_force_phys") is not None
        and "final_force_phys" not in out
    ):
        out["final_force_phys"] = evidence["final_force_phys"]
    return out


def _frontier_from_mapping(
    mapping: Mapping[str, Any],
    *,
    summary_path: str,
    function: str | None,
    artifact: Path,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(function, str) or not function:
        function = _infer_function_from_mapping(mapping)
    if not isinstance(function, str) or not function:
        return None
    if mapping.get("status") == "not-present":
        return None
    if _is_post_ceiling_continuation_ranked_candidate_row(summary_path):
        return None
    if _is_inline_leverage_strict_record(mapping):
        return _inline_leverage_boundary_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_normalized_frontier_mapping(mapping):
        return _normalized_frontier_mapping(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_draw_helper_boundary_retained_score_rows_terminal(mapping, function):
        return _draw_helper_boundary_retained_score_rows_terminal_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_draw_protected_expression_reconcile_terminal_artifact(mapping, function):
        return _draw_protected_expression_reconcile_terminal_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_draw_helper_boundary_suggest_inlines_terminal(mapping, function):
        return _draw_helper_boundary_suggest_inlines_terminal_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_post_source_context_next_dimension_artifact(mapping):
        return _post_source_context_next_dimension_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_post_meta_source_model_synthesis_artifact(mapping, function):
        return _post_meta_source_model_synthesis_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_sort_protected_structural_recombine_artifact(mapping, function):
        return _sort_protected_structural_recombine_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_sort_cross_tu_recombine_artifact(mapping, function):
        return _sort_cross_tu_recombine_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_scoped_direct_sort_score_source_artifact(mapping):
        return _scoped_direct_sort_score_source_frontier(
            mapping,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_post_ceiling_source_model_proof(mapping):
        return _post_ceiling_source_model_proof_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )

    key = summary_path.rsplit(".", 1)[-1] if summary_path else ""
    kind = mapping.get("kind")
    if (
        kind == "retained-source-select-order-repair"
        and _non_empty_str(mapping.get("command"))
    ):
        return _retained_select_order_repair_frontier(
            mapping,
            context=context or {},
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if key == "terminal_exhaustion_summary" and kind in _SELECT_ORDER_TERMINAL_KINDS:
        return _select_order_case_c_terminal_frontier(
            mapping,
            context=context or {},
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if (
        key == "terminal_summary"
        and kind in _POST_CEILING_BASELINE_ESCAPE_KINDS
    ) or kind in _POST_CEILING_BASELINE_ESCAPE_KINDS:
        return _post_ceiling_baseline_escape_terminal_frontier(
            mapping,
            context=context or {},
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if (
        key == "post_ceiling_continuation_summary"
        or kind
        in {
            _POST_CEILING_CONTINUATION_KIND,
            _POST_CEILING_CONTINUATION_TERMINAL_KIND,
        }
    ):
        return _post_ceiling_continuation_frontier(
            mapping,
            context=context or {},
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if kind == _ADDI_RESOLVER_KIND:
        return _target_only_addi_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if (
        key == "target_only_backprojection_source_probe_continuation"
        or summary_path.endswith(
            "target_only_allocator_backprojection.source_probe_continuation"
        )
        or kind == "target-only-backprojection-source-probe-continuation"
    ):
        return _target_only_addi_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if (
        key == "target_only_c2_sticky_pool_attribution"
        or summary_path.endswith(
            "target_only_allocator_backprojection.c2_sticky_pool_attribution"
        )
        or kind == "target-only-c2-sticky-pool-source-attribution"
    ):
        return _target_only_c2_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if key == "copy_survived_repair" or mapping.get("transform_category") == (
        "copy-survived"
    ):
        return _copy_survived_repair_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if _is_node_set_split_exhaustion(mapping):
        return _copy_survived_node_set_terminal_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    if key in _SUMMARY_KEYS or (
        _is_retained_summary_kind(kind)
        and _non_empty_str(mapping.get("status")) is not None
    ):
        return _retained_summary_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    return None


def _is_scoped_direct_sort_score_source_artifact(mapping: Mapping[str, Any]) -> bool:
    if mapping.get("function") != _SORT_FUNCTION:
        return False
    if mapping.get("full_unit_source") is not True:
        return False
    if not isinstance(mapping.get("target_score"), Mapping):
        return False
    return bool(
        _direct_sort_score_source_source(mapping)
        or _direct_sort_score_source_candidate_id(mapping)
    )


def _scoped_direct_sort_score_source_frontier(
    mapping: Mapping[str, Any],
    *,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any] | None:
    candidate_id = _direct_sort_score_source_candidate_id(mapping)
    dimension_id = _non_empty_str(mapping.get("dimension_id"))
    inferred_dimension = _dimension_from_candidate_id(candidate_id)
    dimension_id = dimension_id or inferred_dimension
    if dimension_id not in {
        _SORT_SWAP_SLOT_LVALUE_DIMENSION,
        _SORT_SEMANTIC_RECOMBINE_DIMENSION,
    }:
        return None

    source = _direct_sort_score_source_source(mapping)
    final_force = (
        _direct_sort_score_source_target_force(mapping)
        or dict(_SORT_PROTECTED_STRUCTURAL_TARGETS)
    )
    candidate = _direct_sort_score_source_candidate_row(
        mapping,
        candidate_id=candidate_id,
        dimension_id=dimension_id,
        source=source,
    )
    terminal = _direct_sort_score_source_explicit_terminal(mapping, dimension_id)
    frontier = _base_frontier(
        mapping,
        function=_SORT_FUNCTION,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_SORT_DIRECT_SCORE_SOURCE_FAMILY,
        frontier_id=_frontier_id(
            _SORT_FUNCTION,
            _SORT_DIRECT_SCORE_SOURCE_FAMILY,
            ("dimension", dimension_id),
            ("candidate", candidate_id or ""),
            ("source", source or ""),
        ),
        attempted=final_force,
        protected={},
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = _SORT_DIRECT_SCORE_SOURCE_FAMILY
    frontier["status"] = str(
        mapping.get("status") or ("terminal" if terminal else "score-source")
    )
    frontier["dimension_id"] = dimension_id
    frontier["source_model_layer_dimension_id"] = dimension_id
    frontier["candidate_id"] = candidate_id
    frontier["source_file"] = source
    frontier["source_retained"] = source
    frontier["best_candidate"] = candidate
    frontier["target_hits"] = _hit_map(candidate, final_force)
    frontier["protected_hits"] = {}
    frontier["normalized_drift"] = _normalized_drift(candidate)
    frontier["source_model_proof"] = _direct_sort_score_source_model_proof(
        candidate,
        dimension_id=dimension_id,
        terminal=terminal,
    )
    if not terminal:
        continuation: dict[str, Any] = {
            "route": "score-source",
            "candidate_id": candidate_id,
            "dimension_id": dimension_id,
            "target_score": dict(mapping["target_score"]),
        }
        if source is not None:
            continuation["source_retained"] = source
            continuation["command"] = _score_source_command(source, _SORT_FUNCTION)
        frontier["continuation"] = continuation
        frontier["actionable"] = _retained_meta_continuation_has_action(continuation)
    return frontier


def _direct_sort_score_source_source(mapping: Mapping[str, Any]) -> str | None:
    return _non_empty_str(
        mapping.get("source_retained")
        or mapping.get("source_file")
        or mapping.get("c_file")
    )


def _direct_sort_score_source_candidate_id(mapping: Mapping[str, Any]) -> str | None:
    candidate_id = _non_empty_str(mapping.get("candidate_id"))
    if candidate_id is not None:
        return candidate_id
    source = _direct_sort_score_source_source(mapping)
    if source is None:
        return None
    return Path(source).stem or None


def _direct_sort_score_source_target_force(
    mapping: Mapping[str, Any],
) -> dict[str, int]:
    target_score = mapping.get("target_score")
    virtuals = target_score.get("virtuals") if isinstance(target_score, Mapping) else None
    if not isinstance(virtuals, Mapping):
        return {}
    out: dict[str, int] = {}
    for virtual, row in virtuals.items():
        if not isinstance(row, Mapping):
            continue
        expected = _register_num(row.get("expected"))
        if expected is not None:
            out[str(virtual)] = expected
    return out


def _direct_sort_score_source_candidate_row(
    mapping: Mapping[str, Any],
    *,
    candidate_id: str | None,
    dimension_id: str,
    source: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "dimension_id": dimension_id,
        "source_model_layer_dimension_id": dimension_id,
        "target_score": dict(mapping["target_score"]),
        "full_unit_source": True,
    }
    if source is not None:
        row["source_retained"] = source
        row["source_file"] = source
    for key in (
        "c_file",
        "cflags_from",
        "pcdump_path",
        "score",
        "score_function",
        "expression_score",
        "structural_guard",
        "structural_guard_error",
        "target_matched",
        "target_targeted",
        "target_virtual_distance",
        "expression_matched",
        "expression_targeted",
        "expression_virtual_distance",
    ):
        if mapping.get(key) is not None:
            row[key] = mapping[key]
    target_score = row["target_score"]
    if isinstance(target_score, Mapping):
        row.setdefault("target_matched", _to_int(target_score.get("matched")))
        row.setdefault("target_targeted", _to_int(target_score.get("targeted")))
        row.setdefault(
            "target_virtual_distance",
            _to_int(target_score.get("virtual_distance")),
        )
    return row


def _direct_sort_score_source_explicit_terminal(
    mapping: Mapping[str, Any],
    dimension_id: str,
) -> bool:
    status = str(mapping.get("status") or "")
    has_terminal_marker = (
        mapping.get("terminal") is True
        or status in _TERMINAL_STATUSES
        or mapping.get("terminal_reason") is not None
        or mapping.get("terminal_blocker") is not None
    )
    if not has_terminal_marker:
        return False
    return _direct_sort_score_source_has_exhausted_dimension(mapping, dimension_id)


def _direct_sort_score_source_has_exhausted_dimension(
    mapping: Mapping[str, Any],
    dimension_id: str,
) -> bool:
    if mapping.get("exhausted_source_dimension") == dimension_id:
        return True
    for row in _source_model_synthesis_mapping_list(mapping, "exhausted_dimensions"):
        if row.get("dimension_id") == dimension_id:
            return True
    return False


def _direct_sort_score_source_model_proof(
    candidate: Mapping[str, Any],
    *,
    dimension_id: str,
    terminal: bool,
) -> dict[str, Any]:
    candidate_id = _non_empty_str(candidate.get("candidate_id"))
    synthesis: dict[str, Any] = {
        "status": "score-source",
        "evidence_status": "direct-score-source",
        "attempted_equivalence_classes": [dimension_id],
        "candidate_scores": [dict(candidate)],
        "retained_scored_probes": [dict(candidate)],
        "scored_candidate_ids": [candidate_id] if candidate_id is not None else [],
        "all_candidate_ids": [candidate_id] if candidate_id is not None else [],
        "candidate_count": 1,
        "scored_count": 1,
    }
    proof = {
        "candidate_scores": [dict(candidate)],
        "attempted_equivalence_classes": [dimension_id],
        "source_family_synthesis": synthesis,
    }
    if terminal:
        exhausted = [{"dimension_id": dimension_id, "status": "scored-terminal"}]
        synthesis["status"] = "synthesis-exhausted"
        synthesis["exhausted_dimensions"] = exhausted
        proof["exhausted_dimensions"] = exhausted
    return proof


def _is_draw_helper_boundary_retained_score_rows_terminal(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if function != _DRAW_FUNCTION:
        return False
    rows = _draw_helper_boundary_retained_score_rows(mapping)
    if not rows:
        return False
    if not any(_draw_helper_boundary_score_row_has_retained_source(row) for row in rows):
        return False
    return all(
        _draw_helper_boundary_score_row_expression_matched(row) <= 0 for row in rows
    ) or _draw_helper_boundary_score_rows_have_no_structural_target_progress(rows)


def _is_draw_protected_expression_reconcile_terminal_artifact(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if function != _DRAW_FUNCTION:
        return False
    if mapping.get("class_id") != _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_CLASS_ID:
        return False
    status = str(mapping.get("status") or "")
    if status not in {"blocked", "terminal", "exhausted"}:
        return False
    blockers = _draw_protected_expression_reconcile_blockers(mapping)
    return bool(blockers)


def _draw_protected_expression_reconcile_terminal_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    final_force = _draw_protected_expression_reconcile_force(mapping)
    blockers = _draw_protected_expression_reconcile_blockers(mapping)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        frontier_id=_frontier_id(
            function,
            _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
            ("terminal", _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON),
            ("force", final_force),
        ),
        attempted=final_force,
        protected={},
        final_force=final_force,
        terminal=True,
    )
    frontier["kind"] = _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_CLASS_ID
    frontier["status"] = "terminal"
    frontier["terminal_reason"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    )
    frontier["terminal_blocker"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    )
    frontier["terminal_blockers"] = blockers
    frontier["suppression_family"] = _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE
    frontier["next_unsupported_source_model"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
    )
    frontier["next_unsupported_source_family"] = (
        _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    frontier["exhausted_dimensions"] = [
        {
            "dimension_id": _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
            "status": "scored-terminal",
            "exhaustion_reason": (
                _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
            ),
        }
    ]
    frontier["candidate_count"] = _to_int(mapping.get("generated_count")) or len(
        [row for row in mapping.get("candidates") or [] if isinstance(row, Mapping)]
    )
    frontier["scored_count"] = _to_int(mapping.get("scored_count"))
    frontier["_final_force_phys"] = dict(final_force)
    return frontier


def _draw_protected_expression_reconcile_force(
    mapping: Mapping[str, Any],
) -> dict[str, int]:
    explicit = _normalized_int_mapping(
        mapping.get("final_force_phys") or mapping.get("force_phys")
    )
    if explicit:
        return explicit
    out: dict[str, int] = {}
    raw_requirements = mapping.get("anchor_requirements")
    if isinstance(raw_requirements, Sequence) and not isinstance(
        raw_requirements,
        (str, bytes, bytearray),
    ):
        for row in raw_requirements:
            if not isinstance(row, Mapping):
                continue
            virtual = _to_int(row.get("baseline_virtual") or row.get("virtual"))
            expected = _to_int(row.get("expected") or row.get("target_reg"))
            if virtual is None or expected is None:
                continue
            out[str(virtual)] = expected
    return dict(sorted(out.items(), key=lambda item: _int_sort_key(item[0])))


def _draw_protected_expression_reconcile_blockers(
    mapping: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for key in ("terminal_blockers", "generation_blockers", "blockers"):
        raw = mapping.get(key)
        if isinstance(raw, str):
            blockers.append(raw)
            continue
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            continue
        for item in raw:
            if isinstance(item, Mapping):
                value = (
                    item.get("blocker")
                    or item.get("reason")
                    or item.get("terminal_blocker")
                )
            else:
                value = item
            text = _non_empty_str(value)
            if text is not None:
                blockers.append(text)
    return _dedupe_strings(blockers)


def _draw_helper_boundary_retained_score_rows(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_rows = mapping.get("score_rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        if not _is_draw_helper_boundary_score_row(row):
            continue
        rows.append(dict(row))
    return rows


def _is_draw_helper_boundary_score_row(row: Mapping[str, Any]) -> bool:
    family = _non_empty_str(row.get("family")) or ""
    transform_family = _non_empty_str(row.get("transform_family")) or ""
    dimension = _non_empty_str(row.get("dimension_id")) or ""
    kind = _non_empty_str(row.get("kind")) or ""
    return (
        family == "inline-local-write-helper"
        or transform_family == "inline-local-write-helper"
        or transform_family == "local-write-helper"
        or dimension.startswith("inline-local-write-helper-")
        or "helper-boundary" in kind
        or "helper_boundary" in kind
    )


def _draw_helper_boundary_score_row_has_retained_source(row: Mapping[str, Any]) -> bool:
    has_source = any(
        _non_empty_str(row.get(key)) is not None
        for key in ("source_retained", "source_file", "path", "candidate_path")
    )
    return has_source and _non_empty_str(row.get("pcdump_path")) is not None


def _draw_helper_boundary_score_row_expression_matched(
    row: Mapping[str, Any],
) -> int:
    return (
        _to_int(row.get("expression_matched"))
        or _to_int(_nested_value(row, ("expression_score", "matched")))
        or 0
    )


def _draw_helper_boundary_score_rows_have_no_structural_target_progress(
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    return all(
        _draw_helper_boundary_score_row_target_matched(row) <= 0 for row in rows
    ) and not any(
        _draw_helper_boundary_score_row_structural_accepted(row) for row in rows
    )


def _draw_helper_boundary_score_row_structural_accepted(
    row: Mapping[str, Any],
) -> bool:
    structural = row.get("structural_guard")
    if isinstance(structural, Mapping):
        return structural.get("accepted") is True
    return row.get("structural_guard_accepted") is True


def _draw_helper_boundary_score_row_target_matched(row: Mapping[str, Any]) -> int:
    return (
        _to_int(row.get("target_matched"))
        or _to_int(_nested_value(row, ("target_score", "matched")))
        or 0
    )


def _draw_helper_boundary_score_row_target_targeted(row: Mapping[str, Any]) -> int:
    return (
        _to_int(row.get("target_targeted"))
        or _to_int(_nested_value(row, ("target_score", "targeted")))
        or 0
    )


def _draw_helper_boundary_score_row_expression_targeted(
    row: Mapping[str, Any],
) -> int:
    return (
        _to_int(row.get("expression_targeted"))
        or _to_int(_nested_value(row, ("expression_score", "targeted")))
        or 0
    )


def _draw_helper_boundary_retained_score_row_ids(
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    out: list[str] = []
    for index, row in enumerate(rows, start=1):
        candidate_id = _non_empty_str(row.get("candidate_id")) or f"row-{index}"
        if candidate_id not in out:
            out.append(candidate_id)
    return out


def _draw_helper_boundary_retained_score_row_blockers(
    rows: Sequence[Mapping[str, Any]],
    *,
    candidate_ids: Sequence[str],
) -> list[dict[str, Any]]:
    blockers = [
        {
            "reason": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
            "count": len(candidate_ids),
            "candidate_ids": list(candidate_ids),
        },
        {"reason": "no-expression-floor-improvement", "count": len(rows)},
        {"reason": "no-protected-expression-improvement", "count": len(rows)},
    ]
    for row in rows:
        candidate_id = _non_empty_str(row.get("candidate_id"))
        for blocker in row.get("blockers") or []:
            if isinstance(blocker, Mapping):
                reason = _non_empty_str(
                    blocker.get("reason")
                    or blocker.get("terminal_blocker")
                    or blocker.get("blocker")
                )
            else:
                reason = _non_empty_str(blocker)
            if reason is None:
                continue
            entry: dict[str, Any] = {"reason": reason}
            if candidate_id is not None:
                entry["candidate_ids"] = [candidate_id]
            blockers.append(entry)
    return _dedupe_dicts(blockers)


def _draw_helper_boundary_compact_score_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for key in (
            "candidate_id",
            "family",
            "transform_family",
            "dimension_id",
            "variant_id",
            "source_retained",
            "source_file",
            "pcdump_path",
            "target_matched",
            "target_targeted",
            "target_virtual_distance",
            "expression_matched",
            "expression_targeted",
            "expression_virtual_distance",
            "normalized_diff_lines",
            "match_percent",
        ):
            value = row.get(key)
            if value is not None:
                item[key] = value
        structural = row.get("structural_guard")
        if isinstance(structural, Mapping):
            item["structural_guard"] = {
                key: value
                for key, value in structural.items()
                if key
                in {
                    "accepted",
                    "classification_primary",
                    "normalized_diff_lines",
                    "frame_delta",
                    "rejection_reason",
                }
                and value is not None
            }
        blockers = [
            dict(blocker) if isinstance(blocker, Mapping) else {"reason": str(blocker)}
            for blocker in (row.get("blockers") or [])
        ]
        if blockers:
            item["blockers"] = blockers
        compact.append(item)
    return compact


def _draw_helper_boundary_retained_score_rows_terminal_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    rows = _draw_helper_boundary_retained_score_rows(mapping)
    candidate_ids = _draw_helper_boundary_retained_score_row_ids(rows)
    terminal_blockers = _draw_helper_boundary_retained_score_row_blockers(
        rows,
        candidate_ids=candidate_ids,
    )
    compact_rows = _draw_helper_boundary_compact_score_rows(rows)
    final_force = _source_model_force_from_score_rows(rows)
    best_target_matched = max(
        (_draw_helper_boundary_score_row_target_matched(row) for row in rows),
        default=0,
    )
    best_expression_matched = max(
        (_draw_helper_boundary_score_row_expression_matched(row) for row in rows),
        default=0,
    )
    best_target_targeted = max(
        (_draw_helper_boundary_score_row_target_targeted(row) for row in rows),
        default=len(final_force) or 0,
    )
    best_expression_targeted = max(
        (_draw_helper_boundary_score_row_expression_targeted(row) for row in rows),
        default=len(final_force) or 0,
    )
    score_coverage = {
        "scored_rows": len(rows),
        "source_retained_rows": sum(
            1 for row in rows if _draw_helper_boundary_score_row_has_retained_source(row)
        ),
        "best_target_matched": best_target_matched,
        "best_target_targeted": best_target_targeted,
        "best_expression_matched": best_expression_matched,
        "best_expression_targeted": best_expression_targeted,
        "expression_improved_rows": sum(
            1 for row in rows if _draw_helper_boundary_score_row_expression_matched(row) > 0
        ),
    }
    exhausted_dimensions = [
        {
            "dimension_id": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": (
                _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
            ),
            "candidate_ids": list(candidate_ids),
        }
    ]
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        frontier_id=_frontier_id(
            function,
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
            (
                "terminal",
                _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
            ),
            ("candidates", candidate_ids),
        ),
        attempted=final_force,
        protected=final_force,
        final_force=final_force,
        terminal=True,
    )
    source_family_synthesis = {
        "status": "terminal",
        "evidence_status": "artifact-synthesis-data",
        "artifact_kind": "debug-suggest-inlines-retained-source",
        "terminal_reason": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        ),
        "terminal_blocker": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        ),
        "terminal_blockers": terminal_blockers,
        "attempted_equivalence_classes": [
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ],
        "exhausted_dimensions": exhausted_dimensions,
        "candidate_count": len(candidate_ids),
        "scored_count": len(rows),
        "score_coverage": score_coverage,
        "candidate_scores": compact_rows,
        "retained_scored_probes": compact_rows,
        "all_candidate_ids": list(candidate_ids),
        "closed_families": [_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY],
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "exhausted_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "next_unsupported_source_family": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
        ),
    }
    source_model_proof = {
        "kind": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_KIND,
        "status": "terminal",
        "terminal_reason": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        ),
        "terminal_blocker": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        ),
        "terminal_blockers": terminal_blockers,
        "attempted_equivalence_classes": [
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ],
        "exhausted_dimensions": exhausted_dimensions,
        "candidate_scores": compact_rows,
        "retained_scored_probes": compact_rows,
        "score_coverage": score_coverage,
        "closed_families": [_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY],
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "exhausted_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "next_unsupported_source_family": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
        ),
        "source_family_synthesis": source_family_synthesis,
    }
    frontier.update({
        "kind": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_KIND,
        "status": "terminal",
        "terminal_reason": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        ),
        "terminal_blocker": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        ),
        "terminal_blockers": terminal_blockers,
        "suppression_family": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        "closed_families": [_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY],
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "exhausted_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "next_unsupported_source_family": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
        ),
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "scored_count": len(rows),
        "score_coverage": score_coverage,
        "candidate_scores": compact_rows,
        "retained_scored_probes": compact_rows,
        "source_model_proof": source_model_proof,
    })
    return frontier


def _is_draw_helper_boundary_suggest_inlines_terminal(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if function != _DRAW_FUNCTION:
        return False
    if mapping.get("status") != "terminal":
        return False
    if (
        _non_empty_str(mapping.get("terminal_blocker"))
        != _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON
    ):
        return False
    candidates = mapping.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return False
    if not candidates:
        return False
    patches = mapping.get("patches")
    scores = mapping.get("scores")
    return not patches and not scores


def _draw_helper_boundary_suggest_inlines_terminal_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    candidate_ids = _draw_helper_boundary_suggest_inlines_candidate_ids(mapping)
    terminal_blockers = _draw_helper_boundary_suggest_inlines_terminal_blockers(
        mapping,
        candidate_ids=candidate_ids,
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        frontier_id=_frontier_id(
            function,
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
            ("terminal", _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON),
            ("candidates", candidate_ids),
        ),
        attempted={},
        protected={},
        final_force={},
        terminal=True,
    )
    source_family_synthesis = {
        "status": "terminal",
        "evidence_status": "artifact-synthesis-data",
        "artifact_kind": "suggest-inlines-terminal",
        "attempted_equivalence_classes": [
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ],
        "exhausted_dimensions": [
            {
                "dimension_id": (
                    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
                ),
                "exhaustion_reason": (
                    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON
                ),
            }
        ],
        "terminal_blocker": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blockers": terminal_blockers,
        "candidate_count": len(candidate_ids),
        "all_candidate_ids": candidate_ids,
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "exhausted_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "next_unsupported_source_family": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
        ),
    }
    source_model_proof = {
        "kind": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_KIND,
        "status": "terminal",
        "terminal_reason": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blocker": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blockers": terminal_blockers,
        "attempted_equivalence_classes": [
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ],
        "exhausted_dimensions": [
            {
                "dimension_id": (
                    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
                ),
                "exhaustion_reason": (
                    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON
                ),
            }
        ],
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "exhausted_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "next_unsupported_source_family": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
        ),
        "source_family_synthesis": source_family_synthesis,
    }
    frontier.update({
        "kind": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_KIND,
        "status": "terminal",
        "terminal_reason": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blocker": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
        "suppression_family": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY,
        "unsupported_source_expression_class": (
            _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
        ),
        "exhausted_source_dimension": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION
        ),
        "next_unsupported_source_family": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            _DRAW_COUPLED_FPR_HELPER_BOUNDARY_FINAL_MODEL
        ),
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "terminal_blockers": terminal_blockers,
        "source_model_proof": source_model_proof,
    })
    messages = [
        str(item) for item in (mapping.get("messages") or [])
        if isinstance(item, str) and item
    ]
    if messages:
        frontier["messages"] = messages[:5]
    rejection_reasons = _draw_helper_boundary_suggest_inlines_rejection_reasons(
        mapping
    )
    if rejection_reasons:
        frontier["rejection_reasons"] = rejection_reasons
    return frontier


def _draw_helper_boundary_suggest_inlines_candidate_ids(
    mapping: Mapping[str, Any],
) -> list[str]:
    out: list[str] = []
    candidates = mapping.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return out
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = _non_empty_str(candidate.get("candidate_id"))
        if candidate_id is not None and candidate_id not in out:
            out.append(candidate_id)
    return out


def _draw_helper_boundary_suggest_inlines_terminal_blockers(
    mapping: Mapping[str, Any],
    *,
    candidate_ids: Sequence[str],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if candidate_ids:
        blockers.append({
            "reason": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
            "count": len(candidate_ids),
            "candidate_ids": list(candidate_ids),
        })
    raw_blockers = mapping.get("terminal_blockers")
    if isinstance(raw_blockers, Sequence) and not isinstance(raw_blockers, (str, bytes)):
        for raw in raw_blockers:
            if isinstance(raw, Mapping):
                reason = _non_empty_str(
                    raw.get("reason")
                    or raw.get("terminal_blocker")
                    or raw.get("blocker")
                )
                if reason is None:
                    continue
                blocker = {"reason": reason}
                count = _to_int(raw.get("count"))
                if count is not None:
                    blocker["count"] = count
                ids = [
                    str(item) for item in (raw.get("candidate_ids") or [])
                    if isinstance(item, str) and item
                ]
                if ids:
                    blocker["candidate_ids"] = ids
                blockers.append(blocker)
            else:
                reason = _non_empty_str(raw)
                if reason is not None:
                    blockers.append({"reason": reason})
    if not blockers:
        blockers.append({
            "reason": _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON,
        })
    return _dedupe_dicts(blockers)


def _draw_helper_boundary_suggest_inlines_rejection_reasons(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    candidates = mapping.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        reason = _non_empty_str(candidate.get("rejection_reason"))
        if reason is None:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items())
    ]


def _infer_function_from_mapping(mapping: Mapping[str, Any]) -> str | None:
    value = _non_empty_str(mapping.get("function"))
    if value is not None:
        return value
    for key in ("plan", "request", "validation_summary"):
        nested = mapping.get(key)
        if isinstance(nested, Mapping):
            value = _non_empty_str(nested.get("function"))
            if value is not None:
                return value
    if _is_sort_protected_structural_recombine_artifact(mapping, _SORT_FUNCTION):
        return _SORT_FUNCTION
    if mapping.get("class_id") == _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_CLASS_ID:
        return _DRAW_FUNCTION
    for row in mapping.get("combinations") or []:
        if not isinstance(row, Mapping):
            continue
        command = _nested_value(row, ("score_result", "command"))
        inferred = _function_from_command(command)
        if inferred is not None:
            return inferred
        stdout = _nested_value(row, ("score_result", "parsed_json", "function"))
        inferred = _non_empty_str(stdout)
        if inferred is not None:
            return inferred
    return None


def _is_post_source_context_next_dimension_artifact(
    entry: Mapping[str, Any],
) -> bool:
    return entry.get("kind") == POST_SOURCE_CONTEXT_DISCOVERY_KIND


def _post_source_context_next_dimension_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    status = str(mapping.get("status") or "")
    next_frontier = (
        mapping.get("next_frontier")
        if isinstance(mapping.get("next_frontier"), Mapping)
        else {}
    )
    probe = _post_source_context_discovery_probe(mapping, next_frontier)
    attempted = _normalized_int_mapping(
        mapping.get("attempted_targets")
        or next_frontier.get("attempted_targets")
        or _post_source_context_score_force(probe)
    )
    final_force = _normalized_int_mapping(
        mapping.get("final_force_phys") or next_frontier.get("final_force_phys")
    )
    if not final_force:
        final_force = dict(attempted)
    terminal = status != "source-actionable"
    frontier_dimension = (
        mapping.get("next_unsupported_source_dimension")
        or next_frontier.get("dimension_id")
        or mapping.get("exhausted_source_dimension")
        or mapping.get("trigger_dimension")
        or DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=POST_SOURCE_CONTEXT_DISCOVERY_FAMILY,
        frontier_id=_frontier_id(
            function,
            POST_SOURCE_CONTEXT_DISCOVERY_FAMILY,
            ("status", status),
            ("dimension", frontier_dimension),
            ("candidate", probe.get("candidate_id")),
        ),
        attempted=attempted,
        protected={},
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = POST_SOURCE_CONTEXT_DISCOVERY_KIND
    frontier["suppression_family"] = POST_SOURCE_CONTEXT_DISCOVERY_FAMILY
    frontier["status"] = status
    frontier["target_score"] = probe.get("target_score")
    frontier["expression_score"] = probe.get("expression_score")
    if status == "source-actionable":
        continuation = (
            dict(next_frontier.get("continuation"))
            if isinstance(next_frontier.get("continuation"), Mapping)
            else {}
        )
        continuation.setdefault("route", DRAW_POST_SOURCE_CONTEXT_DIMENSION)
        for key in (
            "candidate_id",
            "source_hunks",
            "source_retained",
            "source_components",
            "pcdump_path",
            "target_score",
            "expression_score",
            "ranked_retained_c_probes",
        ):
            if key == "ranked_retained_c_probes":
                value = mapping.get(key)
            else:
                value = probe.get(key)
            if value is not None and value != []:
                continuation[key] = value
        frontier["terminal"] = False
        frontier["terminal_reason"] = None
        frontier["actionable"] = True
        frontier["continuation"] = continuation
        frontier["ranked_retained_c_probes"] = [
            dict(row) for row in mapping.get("ranked_retained_c_probes") or []
            if isinstance(row, Mapping)
        ]
        return frontier

    frontier["terminal"] = True
    terminal_reason = (
        "post-source-context-next-dimension/"
        f"{status or 'unsupported-source-dimension'}"
    )
    frontier["terminal_reason"] = terminal_reason
    frontier["actionable"] = False
    frontier["continuation"] = None
    next_dimension = mapping.get("next_unsupported_source_dimension")
    exhausted_dimensions = _post_source_context_exhausted_dimensions(mapping)
    if (
        isinstance(next_dimension, str)
        and next_dimension
        and next_dimension not in set(exhausted_dimensions)
    ):
        frontier["next_unsupported_source_dimension"] = next_dimension
    retained_rows = _post_source_context_retained_rows(mapping)
    proof = {
        "kind": POST_SOURCE_CONTEXT_DISCOVERY_KIND,
        "status": "complete",
        "reason": "post-source-context-next-dimension-discovered",
        "terminal_reason": terminal_reason,
        "attempted_equivalence_classes": exhausted_dimensions,
        "exhausted_dimensions": exhausted_dimensions,
        "next_unsupported_source_family": mapping.get(
            "next_unsupported_source_family"
        ),
        "next_unsupported_source_model": mapping.get(
            "next_unsupported_source_model"
        ),
        "next_unsupported_source_spans": [
            dict(row) for row in mapping.get("source_spans") or []
            if isinstance(row, Mapping)
        ],
        "source_spans": [
            dict(row) for row in mapping.get("source_spans") or []
            if isinstance(row, Mapping)
        ],
        "candidate_scores": retained_rows,
        "retained_scored_probes": retained_rows,
        "target_score": probe.get("target_score"),
        "expression_score": probe.get("expression_score"),
    }
    if (
        isinstance(next_dimension, str)
        and next_dimension
        and next_dimension not in set(exhausted_dimensions)
    ):
        proof["next_unsupported_source_dimension"] = next_dimension
    for key in (
        "exhausted_source_dimension",
        "unsupported_source_expression_class",
        "unsupported_source_expression_model",
    ):
        value = mapping.get(key)
        if value is not None:
            proof[key] = value
    frontier["source_model_proof"] = proof
    return frontier


def _post_source_context_exhausted_dimensions(
    mapping: Mapping[str, Any],
) -> list[str]:
    values: list[Any] = []
    exhausted = mapping.get("exhausted_dimensions")
    if isinstance(exhausted, list):
        for row in exhausted:
            if isinstance(row, Mapping):
                values.append(row.get("dimension_id"))
            else:
                values.append(row)
    values.append(mapping.get("exhausted_source_dimension"))
    values.append(mapping.get("trigger_dimension"))
    dimensions = _dedupe_strings(values)
    return dimensions or [DRAW_POST_SOURCE_CONTEXT_DIMENSION]


def _post_source_context_discovery_probe(
    mapping: Mapping[str, Any],
    next_frontier: Mapping[str, Any],
) -> dict[str, Any]:
    retained_rows = _post_source_context_retained_rows(mapping)
    if retained_rows:
        return retained_rows[0]
    continuation = next_frontier.get("continuation")
    if isinstance(continuation, Mapping):
        return dict(continuation)
    return {}


def _post_source_context_retained_rows(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return _dedupe_dicts(
        [
            dict(row)
            for key in (
                "ranked_retained_c_probes",
                "retained_evidence",
                "candidate_scores",
                "retained_scored_probes",
            )
            for row in mapping.get(key) or []
            if isinstance(row, Mapping)
        ]
    )


def _post_source_context_score_force(row: Mapping[str, Any]) -> dict[str, int]:
    score = row.get("target_score")
    if not isinstance(score, Mapping):
        score = row.get("expression_score")
    if not isinstance(score, Mapping):
        return {}
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}
    out: dict[str, int] = {}
    for virtual, payload in virtuals.items():
        if not isinstance(payload, Mapping):
            continue
        expected = _register_num(payload.get("expected"))
        if expected is not None:
            out[str(virtual)] = expected
    return out


def _function_from_command(command: Any) -> str | None:
    if isinstance(command, str):
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
    elif isinstance(command, Sequence) and not isinstance(
        command,
        (bytes, bytearray),
    ):
        parts = [str(part) for part in command]
    else:
        return None
    for index, part in enumerate(parts):
        if part in {"-f", "--function"} and index + 1 < len(parts):
            return _non_empty_str(parts[index + 1])
    return None


def _is_post_ceiling_continuation_ranked_candidate_row(summary_path: str) -> bool:
    parts = summary_path.split(".")
    return (
        len(parts) >= 3
        and "post_ceiling_continuation_summary" in parts
        and parts[-2] == "ranked_candidates"
        and parts[-1].startswith("[")
        and parts[-1].endswith("]")
    )


def _is_inline_leverage_strict_record(mapping: Mapping[str, Any]) -> bool:
    return (
        mapping.get("verdict") == "lever"
        and mapping.get("expansion_form") == "scalar_assignment_splice"
        and _non_empty_str(mapping.get("inline_name")) is not None
        and mapping.get("shape_return") == "scalar"
        and mapping.get("shape_body") == "multi_statement"
    )


def _inline_leverage_boundary_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    inline_name = _non_empty_str(mapping.get("inline_name")) or "<unknown-inline>"
    expansion_form = str(mapping.get("expansion_form") or "")
    attempted = _inline_leverage_boundary_targets(function, mapping)
    final_force = _normalized_force_phys(mapping.get("final_force_phys"))
    if not final_force:
        final_force = dict(attempted)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_INLINE_LEVERAGE_BOUNDARY_FAMILY,
        frontier_id=_inline_leverage_boundary_frontier_id(
            function=function,
            inline_name=inline_name,
            expansion_form=expansion_form,
            final_force=final_force,
        ),
        attempted=attempted,
        protected={},
        final_force=final_force,
        terminal=False,
    )
    frontier["kind"] = _INLINE_LEVERAGE_BOUNDARY_KIND
    frontier["status"] = "source-actionable"
    frontier["suppression_family"] = _INLINE_LEVERAGE_BOUNDARY_FAMILY
    frontier["inline_name"] = inline_name
    frontier["expansion_form"] = expansion_form
    frontier["final_force_phys"] = dict(final_force)
    frontier["shape_body"] = mapping.get("shape_body")
    frontier["shape_return"] = mapping.get("shape_return")
    frontier["def_file"] = mapping.get("def_file")
    frontier["evidence"] = dict(mapping.get("evidence") or {})
    frontier["continuation"] = _inline_leverage_boundary_continuation(
        artifact=artifact,
        function=function,
        inline_name=inline_name,
        attempted=attempted,
    )
    frontier["actionable"] = bool(frontier["continuation"])
    return frontier


def _inline_leverage_boundary_targets(
    function: str,
    mapping: Mapping[str, Any],
) -> dict[str, int]:
    for key in ("attempted_targets", "final_force_phys"):
        targets = _normalized_int_mapping(mapping.get(key))
        if targets:
            return targets
    evidence = mapping.get("evidence")
    if isinstance(evidence, Mapping):
        targets = _normalized_int_mapping(evidence.get("final_force_phys"))
        if targets:
            return targets
    if function == _SORT_FUNCTION:
        return dict(_SORT_INLINE_BOUNDARY_TARGETS)
    return {}


def _inline_leverage_boundary_frontier_id(
    *,
    function: str,
    inline_name: str,
    expansion_form: str,
    final_force: Mapping[str, int],
) -> str:
    return _frontier_id(
        function,
        _INLINE_LEVERAGE_BOUNDARY_FAMILY,
        ("inline", inline_name),
        ("expansion", expansion_form),
        ("force", dict(final_force)),
    )


def _inline_leverage_boundary_continuation(
    *,
    artifact: Path,
    function: str,
    inline_name: str,
    attempted: Mapping[str, int],
) -> dict[str, Any]:
    command = [
        "melee-agent",
        "debug",
        "suggest",
        "inline-boundary-continuation",
        "--inline-leverage-json",
        str(artifact),
        "--function",
        function,
        "--inline-name",
        inline_name,
        "--write-probes",
        (
            "build/diagnostics/inline_boundary/"
            f"{function}__{inline_name}"
        ),
        "--json",
    ]
    for virtual, register in attempted.items():
        command.extend(["--target", f"{virtual}={register}"])
    return {
        "route": "inline-boundary-continuation",
        "command": shlex.join(command),
        "inline_name": inline_name,
        "attempted_targets": dict(attempted),
    }


def _target_only_addi_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    pcode = _normalized_scalar_mapping(mapping.get("pcode_lever"))
    attempted = _normalized_int_mapping(mapping.get("attempted_targets"))
    protected = _normalized_int_mapping(mapping.get("protected_targets"))
    final_force = _normalized_int_mapping(mapping.get("final_force_phys"))
    if not final_force:
        final_force = {**protected, **attempted}
    family_id = _ADDI_FAMILY
    frontier_id = _frontier_id(
        function,
        family_id,
        ("pcode", pcode),
        ("force", final_force),
    )
    terminal = _is_terminal_frontier(mapping)
    best_candidate = _best_candidate_for_mapping(mapping)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=family_id,
        frontier_id=frontier_id,
        attempted=attempted,
        protected=protected,
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = str(mapping.get("kind") or "")
    frontier["pcode_lever"] = pcode
    frontier["suppression_family"] = "addi-copy-product"
    frontier["addi_signature"] = _json_key((pcode, final_force))
    frontier["best_candidate"] = best_candidate
    frontier["continuation"] = (
        None if terminal else _continuation(mapping, best_candidate, function)
    )
    frontier["actionable"] = bool(
        not terminal
        and (
            mapping.get("status") == "source-actionable"
            or _is_actionable_frontier(mapping, best_candidate)
        )
    )
    return frontier


def _target_only_c2_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    final_force = _normalized_int_mapping(mapping.get("final_force_phys"))
    attempted = _normalized_int_mapping(mapping.get("attempted_targets"))
    target_ig = _to_int(mapping.get("target_ig"))
    target_phys = _to_int(mapping.get("target_phys"))
    if not attempted and target_ig is not None:
        if target_phys is None and str(target_ig) in final_force:
            target_phys = final_force[str(target_ig)]
        if target_phys is not None:
            attempted = {str(target_ig): target_phys}
    protected = _normalized_int_mapping(mapping.get("protected_targets"))
    if not protected:
        protected = {
            key: value for key, value in final_force.items()
            if key not in attempted
        }
    if not final_force:
        final_force = {**protected, **attempted}

    class_id = mapping.get("class_id")
    frontier_id = _frontier_id(
        function,
        _C2_FAMILY,
        ("class", class_id),
        ("attempted", attempted),
        ("protected", protected),
        ("force", final_force),
    )
    terminal = _is_terminal_frontier(mapping)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_C2_FAMILY,
        frontier_id=frontier_id,
        attempted=attempted,
        protected=protected,
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = str(
        mapping.get("kind") or "target-only-c2-sticky-pool-source-attribution"
    )
    frontier["class_id"] = class_id
    frontier["suppression_family"] = "c2-sticky-pool"
    frontier["force_signature"] = _force_signature(
        attempted,
        protected,
        final_force,
    )
    frontier["continuation"] = None
    frontier["actionable"] = False
    return frontier


def _copy_survived_repair_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    from_ig = _to_int(mapping.get("from_ig_idx"))
    if from_ig is None:
        from_ig = _to_int(mapping.get("from_virtual"))
    to_ig = _to_int(mapping.get("to_ig_idx"))
    if to_ig is None:
        to_ig = _to_int(mapping.get("to_virtual"))
    from_reg = _to_int(mapping.get("from_assigned_reg"))
    to_reg = _to_int(mapping.get("to_assigned_reg"))
    attempted: dict[str, int] = {}
    if from_ig is not None:
        attempted[str(from_ig)] = from_reg if from_reg is not None else from_ig
    if to_ig is not None:
        attempted[str(to_ig)] = to_reg if to_reg is not None else to_ig
    frontier_id = _frontier_id(
        function,
        _COPY_SURVIVED_FAMILY,
        ("class", mapping.get("class_id")),
        ("from", from_ig),
        ("to", to_ig),
    )
    terminal = (
        mapping.get("status") == "terminal-blocker"
        and _non_empty_str(mapping.get("terminal_blocker")) is not None
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_COPY_SURVIVED_FAMILY,
        frontier_id=frontier_id,
        attempted=attempted,
        protected={},
        final_force=attempted,
        terminal=terminal,
    )
    frontier["kind"] = "copy-survived-pointer-reset"
    frontier["suppression_family"] = _COPY_SURVIVED_FAMILY
    frontier["copy_survived_pair"] = {
        "from_virtual": from_ig,
        "to_virtual": to_ig,
        "from_assigned_reg": from_reg,
        "to_assigned_reg": to_reg,
    }
    frontier["_copy_survived_from_igs"] = [from_ig] if from_ig is not None else []
    route_details = [] if terminal else _copy_survived_route_details(
        mapping,
        function=function,
    )
    frontier["copy_survived_route_signatures"] = [
        detail["signature"] for detail in route_details
    ]
    frontier["copy_survived_route_signature_details"] = route_details
    next_route = next(
        (detail for detail in route_details if detail.get("command")),
        None,
    )
    if next_route is not None:
        frontier["continuation"] = _copy_survived_route_continuation(next_route)
        frontier["actionable"] = True
    else:
        frontier["actionable"] = False
        frontier["continuation"] = None
    return frontier


def _copy_survived_route_details(
    mapping: Mapping[str, Any],
    *,
    function: str,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate_key in ("best_variant", "best_source_candidate"):
        candidate = mapping.get(candidate_key)
        if not isinstance(candidate, Mapping):
            continue
        continuation = candidate.get("continuation")
        if not isinstance(continuation, Mapping):
            continue
        routes = continuation.get("routes")
        if not isinstance(routes, list):
            continue
        for route in routes:
            if not isinstance(route, Mapping):
                continue
            kind = _non_empty_str(route.get("kind"))
            if not kind or not kind.startswith("node-set-split-"):
                continue
            detail = _copy_survived_route_detail(route, function=function)
            if detail is None or detail["signature"] in seen:
                continue
            seen.add(detail["signature"])
            details.append(detail)
    return details


def _copy_survived_route_detail(
    route: Mapping[str, Any],
    *,
    function: str,
) -> dict[str, Any] | None:
    var_name = _non_empty_str(route.get("var"))
    target_ig = _to_int(route.get("target_ig"))
    target_reg = _register_num(route.get("target_reg"))
    current_reg = _register_num(route.get("current_reg"))
    force_phys = _normalized_force_phys(route.get("force_phys"))
    if var_name is None or target_ig is None or target_reg is None:
        return None
    signature = _copy_survived_node_set_route_signature(
        function=function,
        var_name=var_name,
        target_ig=target_ig,
        target_reg=target_reg,
        current_reg=current_reg,
        force_phys=force_phys,
    )
    return {
        "signature": signature,
        "kind": route.get("kind"),
        "var": var_name,
        "target_ig": target_ig,
        "target_reg": target_reg,
        "current_reg": current_reg,
        "force_phys": force_phys,
        "command": _non_empty_str(route.get("command")),
    }


def _copy_survived_route_continuation(
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "route": "command-hint",
        "command": detail.get("command"),
        "route_kind": detail.get("kind"),
        "var": detail.get("var"),
        "target_ig": detail.get("target_ig"),
        "target_reg": detail.get("target_reg"),
        "current_reg": detail.get("current_reg"),
    }


def _is_node_set_split_exhaustion(mapping: Mapping[str, Any]) -> bool:
    if mapping.get("status") != "exhausted":
        return False
    request = mapping.get("request")
    if not isinstance(request, Mapping):
        return False
    if _to_int(request.get("target_ig")) is None:
        return False
    if _register_num(request.get("target_reg")) is None:
        return False
    if _non_empty_str(request.get("var_name")) is None:
        return False
    return bool(
        mapping.get("wrong_register_exhausted") is True
        or mapping.get("wrong_register_or_compile_failed_exhausted") is True
        or mapping.get("terminal_reason") == "all-wrong-register"
        or _node_set_split_exhausted_without_target_progress(mapping, request)
    )


def _node_set_split_exhausted_without_target_progress(
    mapping: Mapping[str, Any],
    request: Mapping[str, Any],
) -> bool:
    pending_count = _to_int(mapping.get("pending_count"))
    if pending_count not in (None, 0):
        return False
    if mapping.get("stop_reason") or mapping.get("stop_condition"):
        return False
    target_ig = _to_int(request.get("target_ig"))
    target_reg = _register_num(request.get("target_reg"))
    if target_ig is None or target_reg is None:
        return False

    seen_scored_candidate = False
    for candidate in mapping.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        objective = candidate.get("objective")
        if not isinstance(objective, Mapping):
            continue
        target_score = objective.get("target_score")
        if not isinstance(target_score, Mapping):
            continue
        virtuals = target_score.get("virtuals")
        if not isinstance(virtuals, Mapping):
            continue
        row = virtuals.get(str(target_ig))
        if not isinstance(row, Mapping):
            continue
        seen_scored_candidate = True
        if row.get("matched") is True or row.get("hit") is True:
            return False
        actual = _register_num(row.get("actual"))
        if actual == target_reg:
            return False
    return seen_scored_candidate


def _copy_survived_node_set_terminal_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any] | None:
    request = mapping.get("request")
    if not isinstance(request, Mapping):
        return None
    var_name = _non_empty_str(request.get("var_name"))
    target_ig = _to_int(request.get("target_ig"))
    target_reg = _register_num(request.get("target_reg"))
    current_reg = _register_num(request.get("current_reg"))
    if var_name is None or target_ig is None or target_reg is None:
        return None
    force_phys = _node_set_split_force_phys(mapping)
    if str(target_ig) not in force_phys:
        force_phys[str(target_ig)] = target_reg
    force_phys = dict(
        sorted(force_phys.items(), key=lambda item: _int_sort_key(item[0]))
    )
    signature = _copy_survived_node_set_route_signature(
        function=function,
        var_name=var_name,
        target_ig=target_ig,
        target_reg=target_reg,
        current_reg=current_reg,
        force_phys=force_phys,
    )
    attempted = {str(target_ig): target_reg}
    protected = {
        key: value for key, value in force_phys.items()
        if key not in attempted
    }
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_COPY_SURVIVED_NODE_SET_TERMINAL_FAMILY,
        frontier_id=_frontier_id(
            function,
            _COPY_SURVIVED_NODE_SET_TERMINAL_FAMILY,
            ("route", signature),
        ),
        attempted=attempted,
        protected=protected,
        final_force=force_phys,
        terminal=True,
    )
    frontier["kind"] = _COPY_SURVIVED_NODE_SET_TERMINAL_KIND
    frontier["terminal_reason"] = _copy_survived_node_set_terminal_reason(mapping)
    frontier["suppression_family"] = _COPY_SURVIVED_FAMILY
    frontier["copy_survived_route_signature"] = signature
    frontier["var"] = var_name
    frontier["target_ig"] = target_ig
    frontier["target_reg"] = target_reg
    frontier["current_reg"] = current_reg
    frontier["final_force_phys"] = dict(force_phys)
    frontier["metrics"]["wrong_register_exhausted"] = mapping.get(
        "wrong_register_exhausted"
    )
    frontier["metrics"]["wrong_register_or_compile_failed_exhausted"] = (
        mapping.get("wrong_register_or_compile_failed_exhausted")
    )
    if mapping.get("terminal_reason") is not None:
        frontier["metrics"]["node_set_terminal_reason"] = mapping.get(
            "terminal_reason"
        )
    return frontier


def _copy_survived_node_set_terminal_reason(mapping: Mapping[str, Any]) -> str:
    if (
        mapping.get("wrong_register_exhausted") is True
        or mapping.get("wrong_register_or_compile_failed_exhausted") is True
        or mapping.get("terminal_reason") == "all-wrong-register"
    ):
        return _COPY_SURVIVED_NODE_SET_ROUTE_TERMINAL_REASON
    return _COPY_SURVIVED_NODE_SET_NO_TARGET_PROGRESS_REASON


def _node_set_split_force_phys(mapping: Mapping[str, Any]) -> dict[str, int]:
    request = mapping.get("request")
    force = _normalized_force_phys(
        request.get("force_phys") if isinstance(request, Mapping) else None
    )
    if force:
        return force
    for candidate in mapping.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        for source in (candidate, candidate.get("objective")):
            if not isinstance(source, Mapping):
                continue
            force = _force_phys_from_target_score(source.get("target_score"))
            if force:
                return force
    return {}


def _force_phys_from_target_score(target_score: Any) -> dict[str, int]:
    if not isinstance(target_score, Mapping):
        return {}
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}
    out: dict[str, int] = {}
    for key, row in virtuals.items():
        if not isinstance(row, Mapping):
            continue
        expected = _to_int(row.get("expected"))
        if expected is None:
            continue
        out[str(key)] = expected
    return dict(sorted(out.items(), key=lambda item: _int_sort_key(item[0])))


def _copy_survived_node_set_route_signature(
    *,
    function: str,
    var_name: str,
    target_ig: int,
    target_reg: int,
    current_reg: int | None,
    force_phys: Mapping[str, int],
) -> str:
    return _json_key({
        "function": function,
        "var": var_name,
        "target_ig": target_ig,
        "target_reg": target_reg,
        "current_reg": current_reg,
        "force": dict(force_phys),
    })


def _is_normalized_frontier_mapping(mapping: Mapping[str, Any]) -> bool:
    return (
        isinstance(mapping.get("frontier_id"), str)
        and isinstance(mapping.get("family_id"), str)
        and isinstance(mapping.get("attempted_targets"), Mapping)
        and "terminal" in mapping
    )


def _normalized_frontier_mapping(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    attempted = _normalized_int_mapping(mapping.get("attempted_targets"))
    protected = _normalized_int_mapping(mapping.get("protected_targets"))
    final_force = _frontier_force_from_targets(mapping, attempted, protected)
    embedded_artifact = Path(_non_empty_str(mapping.get("artifact")) or str(artifact))
    family_id = str(mapping.get("family_id") or "retained-frontier")
    terminal = bool(mapping.get("terminal")) or _is_terminal_frontier(mapping)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=embedded_artifact,
        summary_path=_non_empty_str(mapping.get("summary_path")) or summary_path,
        family_id=family_id,
        frontier_id=str(mapping.get("frontier_id")),
        attempted=attempted,
        protected=protected,
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = str(mapping.get("kind") or family_id)
    frontier["status"] = str(mapping.get("status") or "")
    frontier["terminal_reason"] = (
        _non_empty_str(mapping.get("terminal_reason"))
        or frontier.get("terminal_reason")
    )
    frontier["suppression_family"] = _normalized_suppression_family(mapping)
    frontier["continuation"] = (
        dict(mapping["continuation"])
        if isinstance(mapping.get("continuation"), Mapping)
        and not terminal
        else None
    )
    frontier["actionable"] = bool(
        not terminal
        and isinstance(frontier.get("continuation"), Mapping)
        and _retained_meta_continuation_has_action(frontier["continuation"])
    )
    if isinstance(mapping.get("closed_by"), list):
        frontier["closed_by"] = [
            str(item) for item in mapping["closed_by"] if item
        ]
    frontier["suppressed_by_terminal"] = bool(mapping.get("suppressed_by_terminal"))
    frontier["_final_force_phys"] = dict(final_force)
    for key in (
        "class_id",
        "target_orders",
        "source_file",
        "pcdump",
        "select_order_signature",
        "post_ceiling_route_signature",
        "post_ceiling_route_signatures",
        "post_ceiling_route_signature_details",
        "post_ceiling_continuation_signature",
        "candidate_ids",
        "route_terminal_blockers",
        "blocker_targets",
        "final_force_phys",
        "copy_survived_route_signature",
        "copy_survived_route_signatures",
        "copy_survived_route_signature_details",
        "var",
        "target_ig",
        "target_reg",
        "current_reg",
        "source_model_proof",
        "dimension_id",
        "source_model_layer_dimension_id",
        "candidate_id",
        "best_candidate",
        "terminal_summary",
        "stack_clean_no_anchor_evidence",
        "post_stack_clean_no_anchor_evidence",
        "stack_frame_facts",
        "target_score",
        "expression_score",
        "target_virtual_facts",
        "expression_virtual_facts",
        "source_retained",
        "pcdump_path",
        "source_hunks",
        "terminal_blocker",
        "unsupported_source_expression_class",
        "next_unsupported_source_model",
        "next_unsupported_source_dimension",
        "next_unsupported_source_family",
        "protected_loss_negative_evidence",
        "real_score_authority",
        "terminal_blockers",
        "inline_name",
        "expansion_form",
        "exhausted_dimensions",
        "closed_families",
        "terminal_groups",
        "candidate_count",
        "scored_count",
        "best_score_summary",
    ):
        if mapping.get(key) is not None:
            frontier[key] = mapping[key]
    _enrich_normalized_source_model_proof(
        frontier,
        mapping,
        function=function,
        final_force=final_force,
    )
    stale_reason = _normalized_stale_terminal_reason(frontier)
    if not terminal and stale_reason is not None:
        frontier["terminal"] = True
        frontier["terminal_reason"] = stale_reason
        frontier["actionable"] = False
        frontier["continuation"] = None
        if frontier["artifact"] not in frontier["closed_by"]:
            frontier["closed_by"].append(frontier["artifact"])
    return frontier


def _enrich_normalized_source_model_proof(
    frontier: dict[str, Any],
    mapping: Mapping[str, Any],
    *,
    function: str,
    final_force: Mapping[int, int],
) -> None:
    if _source_model_synthesis_profile(function) is None:
        return
    if frontier.get("family_id") != _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY:
        return
    proof = frontier.get("source_model_proof")
    if not isinstance(proof, Mapping):
        return
    proof = _normalize_existing_source_model_proof(
        frontier,
        proof,
        function=function,
    )
    if isinstance(proof.get("source_family_synthesis"), Mapping):
        return
    candidate_scores_raw = proof.get("candidate_scores")
    if not isinstance(candidate_scores_raw, list):
        return
    candidate_scores = [
        row for row in candidate_scores_raw if isinstance(row, Mapping)
    ]
    synthesis_proof = _source_model_synthesis_proof(
        mapping,
        function=function,
        final_force=final_force,
        candidate_scores=candidate_scores,
    )
    if synthesis_proof is None:
        return
    updated = dict(proof)
    updated["source_family_synthesis"] = synthesis_proof
    updated["attempted_equivalence_classes"] = (
        synthesis_proof["attempted_equivalence_classes"]
    )
    updated["next_unsupported_source_model"] = (
        synthesis_proof["next_unsupported_source_model"]
    )
    frontier["source_model_proof"] = updated
    candidate_ids = synthesis_proof.get("all_candidate_ids")
    if isinstance(candidate_ids, list) and candidate_ids:
        frontier["candidate_ids"] = candidate_ids
    synthesis_count = _to_int(synthesis_proof.get("candidate_count"))
    if synthesis_count is not None:
        frontier["metrics"]["source_model_synthesis_candidate_count"] = (
            synthesis_count
        )


def _normalize_existing_source_model_proof(
    frontier: dict[str, Any],
    proof: Mapping[str, Any],
    *,
    function: str,
) -> Mapping[str, Any]:
    if function != _SORT_FUNCTION:
        return proof
    candidate_scores_raw = proof.get("candidate_scores")
    if not isinstance(candidate_scores_raw, list):
        return proof
    candidate_scores = [
        dict(row) for row in candidate_scores_raw if isinstance(row, Mapping)
    ]
    if not candidate_scores:
        return proof

    updated = dict(proof)
    for row in candidate_scores:
        _classify_source_model_candidate_terminal(row)
    updated["candidate_scores"] = candidate_scores
    expression_anchors = [
        dict(row) for row in (proof.get("expression_anchors") or [])
        if isinstance(row, Mapping)
    ]
    if expression_anchors:
        updated["expression_anchors"] = []
        target_anchors = [
            dict(row) for row in (proof.get("target_anchors") or [])
            if isinstance(row, Mapping)
        ]
        synthesis_proof = proof.get("source_family_synthesis")
        existing_kind = str(frontier.get("kind") or "")
        if existing_kind == _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_KIND:
            proof_kind = existing_kind
            proof_reason = _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_REASON
        else:
            proof_kind, proof_reason = _source_model_proof_kind_reason(
                function=function,
                expression_anchors=[],
                synthesis_proof=(
                    synthesis_proof if isinstance(synthesis_proof, Mapping) else None
                ),
            )
        frontier["kind"] = proof_kind
        frontier["terminal_reason"] = proof_reason
        updated["summary"] = _source_model_proof_summary(
            function=function,
            target_anchors=target_anchors,
            expression_anchors=[],
            candidate_scores=candidate_scores,
        )
    register_class = _source_model_register_class_from_candidate_scores(
        candidate_scores
    )
    if register_class is not None:
        updated["register_class"] = register_class
    profile = _source_model_synthesis_profile(function)
    if profile is not None:
        inferred_dimensions = _dedupe_strings(
            dimension
            for row in candidate_scores
            for dimension in _explicit_or_fallback_source_model_dimensions(
                row,
                profile=profile,
            )
        )
        if inferred_dimensions:
            synthesis = updated.get("source_family_synthesis")
            if isinstance(synthesis, Mapping):
                synthesis_out = dict(synthesis)
                attempted = [
                    item
                    for item in _string_items(
                        synthesis_out.get("attempted_equivalence_classes")
                    )
                    if item in set(_string_items(profile.get("dimensions")))
                ]
                synthesis_out["attempted_equivalence_classes"] = _dedupe_strings(
                    [*attempted, *inferred_dimensions]
                )
                exhausted = []
                for row in _source_model_synthesis_mapping_list(
                    synthesis_out,
                    "exhausted_dimensions",
                ):
                    item = dict(row)
                    if item.get("dimension_id") not in set(
                        _string_items(profile.get("dimensions"))
                    ):
                        item["dimension_id"] = inferred_dimensions[0]
                    exhausted.append(item)
                if exhausted:
                    synthesis_out["exhausted_dimensions"] = exhausted
                updated["source_family_synthesis"] = synthesis_out
                updated["attempted_equivalence_classes"] = (
                    synthesis_out["attempted_equivalence_classes"]
                )
    frontier["source_model_proof"] = updated
    return updated


def _source_model_register_class_from_candidate_scores(
    candidate_scores: Sequence[Mapping[str, Any]],
) -> str | None:
    for row in candidate_scores:
        expression_score = row.get("expression_score")
        if isinstance(expression_score, Mapping):
            register_class = expression_score.get("register_class")
            if register_class:
                return str(register_class)
    return None


def _normalized_stale_terminal_reason(frontier: Mapping[str, Any]) -> str | None:
    family_id = str(frontier.get("family_id") or "")
    if family_id == _COPY_SURVIVED_FAMILY:
        if (
            not frontier.get("continuation")
            and not frontier.get("copy_survived_route_signatures")
        ):
            return "copy-survived-pointer-reset/no-executable-route"
    if family_id == _POST_CEILING_CONTINUATION_FAMILY:
        if (
            not frontier.get("continuation")
            and not frontier.get("post_ceiling_route_signatures")
        ):
            return "post-ceiling-continuation/no-executable-route"
    if family_id == "retained-source-select-order-repair":
        continuation = frontier.get("continuation")
        command = (
            continuation.get("command")
            if isinstance(continuation, Mapping)
            else None
        )
        if (
            isinstance(command, str)
            and " debug target score-source " in f" {command} "
            and "--target" not in command
            and not _frontier_force_for_matching(frontier)
        ):
            return "retained-source-select-order-repair/no-executable-target"
    return None


def _normalized_suppression_family(mapping: Mapping[str, Any]) -> str | None:
    value = _non_empty_str(mapping.get("suppression_family"))
    if value is not None:
        return value
    family_id = str(mapping.get("family_id") or "")
    kind = str(mapping.get("kind") or "")
    if family_id == "retained-source-select-order-repair" or kind in (
        _SELECT_ORDER_TERMINAL_KINDS | {"retained-source-select-order-repair"}
    ):
        return "select-order-case-c-source-exhaustion"
    if family_id == _POST_CEILING_CONTINUATION_FAMILY:
        return _POST_CEILING_CONTINUATION_FAMILY
    if family_id == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY:
        return _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
    if family_id == _POST_CEILING_BASELINE_ESCAPE_FAMILY:
        return _POST_CEILING_BASELINE_ESCAPE_FAMILY
    if family_id == _COPY_SURVIVED_FAMILY:
        return _COPY_SURVIVED_FAMILY
    if family_id == _INLINE_LEVERAGE_BOUNDARY_FAMILY:
        return _INLINE_LEVERAGE_BOUNDARY_FAMILY
    return None


def _frontier_force_from_targets(
    mapping: Mapping[str, Any],
    attempted: Mapping[str, int],
    protected: Mapping[str, int],
) -> dict[str, int]:
    final_force = _normalized_force_phys(mapping.get("_final_force_phys"))
    if not final_force:
        final_force = _normalized_force_phys(mapping.get("final_force_phys"))
    if not final_force:
        final_force = {**protected, **attempted}
    return dict(sorted(final_force.items(), key=lambda item: _int_sort_key(item[0])))


def _is_common_subexpr_residual_hit(mapping: Mapping[str, Any]) -> bool:
    if mapping.get("status") != "residual-hit":
        return False
    kind = str(mapping.get("kind") or mapping.get("family_id") or "")
    if kind in {
        "retained-gpr-common-subexpr-coalesce-source",
        "retained_gpr_common_subexpr_coalesce_source",
    }:
        return True
    return (
        mapping.get("stop_condition")
        == "common-subexpr-coalesce-source-residual-hit"
    )


def _is_common_subexpr_residual_handoff_frontier(
    frontier: Mapping[str, Any],
) -> bool:
    if frontier.get("status") != "residual-hit":
        return False
    if frontier.get("family_id") != "retained_gpr_common_subexpr_coalesce_source":
        return False
    continuation = frontier.get("continuation")
    return (
        isinstance(continuation, Mapping)
        and continuation.get("route") == "retained-common-subexpr-residual-handoff"
    )


def _retained_summary_target_maps(
    mapping: Mapping[str, Any],
    best_candidate: Mapping[str, Any] | None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, Any]]:
    attempted = _normalized_int_mapping(mapping.get("attempted_targets"))
    protected = _normalized_int_mapping(mapping.get("protected_targets"))
    objective = mapping.get("objective")
    final_force = _normalized_int_mapping(mapping.get("final_force_phys"))
    if not final_force and isinstance(objective, Mapping):
        final_force = _normalized_int_mapping(objective.get("final_force_phys"))
    if not final_force:
        final_force = {**protected, **attempted}

    diagnostics: dict[str, Any] = {}
    if _is_common_subexpr_residual_hit(mapping):
        common_force = _normalized_int_mapping(mapping.get("residual_force_phys"))
        preserved = _normalized_int_mapping(mapping.get("preserved_force_phys"))
        if common_force and preserved:
            protected = dict(preserved)
            residual = {
                key: value
                for key, value in common_force.items()
                if key not in protected
            }
            target_score = _candidate_target_score(best_candidate)
            virtuals = target_score.get("virtuals")
            if isinstance(virtuals, Mapping):
                for raw_key, row in virtuals.items():
                    key = str(raw_key)
                    if not isinstance(row, Mapping):
                        continue
                    if row.get("matched") is True and key in preserved:
                        protected[key] = preserved[key]
                    elif row.get("matched") is False and key in common_force:
                        residual.setdefault(key, common_force[key])
            attempted = dict(
                sorted(residual.items(), key=lambda item: _int_sort_key(item[0]))
            )
            protected = dict(
                sorted(protected.items(), key=lambda item: _int_sort_key(item[0]))
            )
            final_force = dict(
                sorted(
                    {**protected, **attempted}.items(),
                    key=lambda item: _int_sort_key(item[0]),
                )
            )
            diagnostics["common_subexpr_force_phys"] = dict(common_force)
            diagnostics["preserved_force_phys"] = dict(preserved)

    final_force = dict(
        sorted(final_force.items(), key=lambda item: _int_sort_key(item[0]))
    )
    return attempted, protected, final_force, diagnostics


def _retained_summary_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    best_candidate = _best_candidate_for_mapping(mapping)
    attempted, protected, final_force, diagnostics = _retained_summary_target_maps(
        mapping,
        best_candidate,
    )
    family_id = _family_id(mapping, summary_path)
    kind = str(mapping.get("kind") or family_id)
    source_owner_sig = _source_owner_signature(mapping)
    frontier_id = _frontier_id(
        function,
        family_id,
        ("kind", kind),
        ("attempted", attempted),
        ("protected", protected),
        ("force", final_force),
        ("source_owner", source_owner_sig),
    )
    terminal = _is_terminal_frontier(mapping)
    continuation = (
        None if terminal else _continuation(mapping, best_candidate, function)
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=family_id,
        frontier_id=frontier_id,
        attempted=attempted,
        protected=protected,
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = kind
    frontier["force_signature"] = _force_signature(
        attempted,
        protected,
        final_force,
    )
    frontier["best_candidate"] = best_candidate
    frontier["target_hits"] = _hit_map(best_candidate, attempted)
    frontier["protected_hits"] = _hit_map(best_candidate, protected)
    frontier["normalized_drift"] = _normalized_drift(best_candidate)
    frontier["continuation"] = continuation
    frontier["actionable"] = bool(
        not terminal and _is_actionable_frontier(mapping, best_candidate)
    )
    for key, value in diagnostics.items():
        frontier[key] = value
    for key in ("closed_families", "terminal_groups"):
        if mapping.get(key) is not None:
            frontier[key] = mapping[key]
    return frontier


def _retained_select_order_repair_frontier(
    mapping: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any] | None:
    command = _non_empty_str(mapping.get("command"))
    parts: list[str] = []
    if command:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []

    class_id = _to_int(context.get("class_id"))
    if class_id is None:
        class_id = _to_int(_command_option(parts, "--class"))

    target_orders = _normalized_target_orders(
        context.get("target_orders")
        if context.get("target_orders") is not None
        else context.get("target_order")
    )
    if not target_orders:
        target_orders = _normalized_target_orders(_command_option(parts, "--target"))

    final_force = _normalized_force_phys(context.get("force_phys_targets"))
    if not final_force:
        final_force = _normalized_force_phys(context.get("force_phys"))
    if not final_force:
        final_force = _normalized_force_phys(context.get("candidate_force_phys"))
    if not final_force:
        final_force = _normalized_force_phys(
            _command_option(parts, "--transform-force-phys")
        )
    if not final_force:
        final_force = _normalized_force_phys(_command_option(parts, "--force-phys"))

    target_ig = _to_int(context.get("target_ig"))
    if target_ig is None and target_orders:
        target_ig = target_orders[-1][1]
    target_phys = _to_int(context.get("target_reg_num"))
    if target_phys is None:
        target_phys = _register_num(context.get("target_reg"))
    if target_phys is None and target_ig is not None:
        target_phys = final_force.get(str(target_ig))

    attempted: dict[str, int] = {}
    if target_ig is not None and target_phys is not None:
        attempted[str(target_ig)] = target_phys
    protected = {
        key: value for key, value in final_force.items()
        if key not in attempted
    }

    route_scoped = (
        context.get("candidate_force_phys") is not None
        or "post_ceiling_continuation_summary" in summary_path
    )
    if route_scoped:
        source_file = (
            _non_empty_str(context.get("source_retained"))
            or _non_empty_str(context.get("source_file"))
            or _non_empty_str(context.get("source"))
            or _command_option(parts, "--source-file")
        )
        pcdump = (
            _non_empty_str(context.get("pcdump_path"))
            or _non_empty_str(context.get("pcdump"))
            or _non_empty_str(context.get("baseline_pcdump_path"))
            or _command_option(parts, "--pcdump")
        )
    else:
        source_file = (
            _non_empty_str(context.get("source_file"))
            or _non_empty_str(context.get("source"))
            or _non_empty_str(context.get("source_retained"))
            or _command_option(parts, "--source-file")
        )
        pcdump = (
            _non_empty_str(context.get("pcdump"))
            or _non_empty_str(context.get("pcdump_path"))
            or _non_empty_str(context.get("baseline_pcdump_path"))
            or _command_option(parts, "--pcdump")
        )
    id_parts: list[tuple[str, Any]] = [
        ("class", class_id),
        ("target_orders", target_orders),
        ("force", final_force),
    ]
    if route_scoped:
        id_parts.extend([
            ("source", _path_signature(source_file)),
            ("pcdump", _path_signature(pcdump)),
        ])
    family_id = "retained-source-select-order-repair"
    frontier_id = _frontier_id(function, family_id, *id_parts)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=family_id,
        frontier_id=frontier_id,
        attempted=attempted,
        protected=protected,
        final_force=final_force,
        terminal=False,
    )
    frontier["kind"] = family_id
    frontier["class_id"] = class_id
    frontier["target_orders"] = target_orders
    frontier["source_file"] = source_file
    frontier["pcdump"] = pcdump
    frontier["suppression_family"] = "select-order-case-c-source-exhaustion"
    frontier["select_order_signature"] = _json_key(
        (class_id, target_orders, final_force)
    )
    frontier["post_ceiling_route_signature"] = _post_ceiling_route_signature(
        route="retained-source-select-order-repair",
        function=function,
        class_id=class_id,
        target_orders=target_orders,
        final_force=final_force,
        source_file=source_file,
        pcdump=pcdump,
    )
    frontier["continuation"] = (
        {"route": "command-hint", "command": command} if command else None
    )
    frontier["actionable"] = bool(command)
    return frontier


def _select_order_case_c_terminal_frontier(
    mapping: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any] | None:
    if mapping.get("status") != "blocked":
        return None
    final_force = _normalized_force_phys(mapping.get("force_phys_targets"))
    if not final_force:
        final_force = _normalized_force_phys(context.get("force_phys_targets"))
    if not final_force:
        final_force = _normalized_force_phys(context.get("force_phys"))
    if not final_force:
        final_force = _normalized_force_phys(context.get("candidate_force_phys"))
    if not final_force:
        return None

    class_id = _to_int(context.get("class_id"))
    target_orders = _normalized_target_orders(context.get("target_orders"))
    if not target_orders:
        target_orders = _normalized_target_orders(context.get("target_order"))
    if not target_orders:
        target_orders = _normalized_target_orders(mapping.get("target_orders"))
    source_file = (
        _non_empty_str(context.get("source_file"))
        or _non_empty_str(context.get("source"))
        or _non_empty_str(context.get("source_retained"))
    )
    pcdump = (
        _non_empty_str(context.get("pcdump"))
        or _non_empty_str(context.get("pcdump_path"))
        or _non_empty_str(context.get("baseline_pcdump_path"))
    )

    blocker_targets = _normalized_int_sequence(mapping.get("blocker_targets"))
    blocker_targets = _select_order_blocker_targets(
        mapping,
        final_force=final_force,
        explicit_targets=blocker_targets,
    )
    attempted = {
        str(target): final_force[str(target)]
        for target in blocker_targets
        if str(target) in final_force
    }
    protected = {
        key: value for key, value in final_force.items()
        if key not in attempted
    }

    family_id = "retained-source-select-order-repair"
    id_parts: list[tuple[str, Any]] = [
        ("class", class_id),
        ("target_orders", target_orders),
        ("force", final_force),
    ]
    if source_file or pcdump:
        id_parts.extend([
            ("source", _path_signature(source_file)),
            ("pcdump", _path_signature(pcdump)),
        ])
    frontier_id = _frontier_id(function, family_id, *id_parts)
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=family_id,
        frontier_id=frontier_id,
        attempted=attempted,
        protected=protected,
        final_force=final_force,
        terminal=True,
    )
    frontier["kind"] = str(
        mapping.get("kind") or "degree-zero-fpr-case-c-source-exhaustion"
    )
    frontier["terminal_reason"] = (
        _non_empty_str(mapping.get("terminal_blocker"))
        or _non_empty_str(mapping.get("dominant_blocker"))
        or frontier["kind"]
    )
    frontier["class_id"] = class_id
    frontier["target_orders"] = target_orders
    frontier["source_file"] = source_file
    frontier["pcdump"] = pcdump
    frontier["suppression_family"] = "select-order-case-c-source-exhaustion"
    frontier["select_order_signature"] = _json_key(
        (class_id, target_orders, final_force)
    )
    frontier["post_ceiling_route_signature"] = _post_ceiling_route_signature(
        route="retained-source-select-order-repair",
        function=function,
        class_id=class_id,
        target_orders=target_orders,
        final_force=final_force,
        source_file=source_file,
        pcdump=pcdump,
    )
    frontier["blocker_targets"] = blocker_targets
    frontier["continuation"] = None
    frontier["actionable"] = False
    for key in (
        "dominant_blocker",
        "terminal_blocker",
        "diagnostic_bucket_counts",
        "best_retained_variant_count",
        "next_source_lever_classes",
    ):
        if key in mapping:
            frontier["metrics"][key] = mapping[key]
    frontier["metrics"]["blocker_targets"] = blocker_targets
    return frontier


def _select_order_blocker_targets(
    mapping: Mapping[str, Any],
    *,
    final_force: Mapping[str, int],
    explicit_targets: Sequence[int],
) -> list[int]:
    out = list(explicit_targets)
    counts = mapping.get("diagnostic_bucket_counts")
    if isinstance(counts, Mapping):
        for key, value in counts.items():
            if not isinstance(key, str) or not key.startswith("force-phys-hit-"):
                continue
            if _to_int(value) != 0:
                continue
            target = _to_int(key.removeprefix("force-phys-hit-"))
            if target is None or str(target) not in final_force:
                continue
            if target not in out:
                out.append(target)
    return out


def _post_ceiling_baseline_escape_terminal_frontier(
    mapping: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    final_force = _normalized_force_phys(
        mapping.get("final_force_phys")
        or context.get("final_force_phys")
        or _nested_mapping(context, ("evidence", "final_force_phys"))
    )
    if not final_force:
        final_force = _post_ceiling_force_from_target_anchors(
            mapping.get("target_anchors")
            or context.get("target_anchors")
            or _nested_mapping(context, ("evidence", "target_anchors"))
        )
    attempted = {
        str(key): value
        for key, value in final_force.items()
    }
    frontier_id = _frontier_id(
        function,
        _POST_CEILING_BASELINE_ESCAPE_FAMILY,
        ("force", final_force),
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_BASELINE_ESCAPE_FAMILY,
        frontier_id=frontier_id,
        attempted=attempted,
        protected={},
        final_force=final_force,
        terminal=True,
    )
    frontier["kind"] = (
        _non_empty_str(mapping.get("kind")) or _POST_CEILING_BASELINE_ESCAPE_KIND
    )
    frontier["final_force_phys"] = dict(final_force)
    frontier["terminal_reason"] = (
        _non_empty_str(mapping.get("terminal_reason"))
        or _POST_CEILING_BASELINE_ESCAPE_REASON
    )
    frontier["suppression_family"] = _POST_CEILING_BASELINE_ESCAPE_FAMILY
    frontier["continuation"] = None
    frontier["actionable"] = False
    embedded_proof = context.get("source_model_proof")
    if isinstance(embedded_proof, Mapping):
        frontier["source_model_proof"] = dict(embedded_proof)
        for key in (
            "next_unsupported_source_model",
            "next_unsupported_source_family",
            "terminal_blockers",
        ):
            value = embedded_proof.get(key)
            if value is not None:
                frontier[key] = value
    for key in (
        "candidate_count",
        "scored_count",
        "best_expression_matched",
        "best_expression_targeted",
        "best_expression_virtual_distance",
    ):
        if mapping.get(key) is not None:
            frontier["metrics"][key] = mapping[key]
            frontier[key] = mapping[key]
    return frontier


def _is_post_meta_source_model_synthesis_artifact(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if _is_actionable_source_model_synthesis_artifact(mapping, function):
        return True
    if function != _SORT_FUNCTION or mapping.get("function") != _SORT_FUNCTION:
        return False
    if mapping.get("status") != "blocked":
        return False
    if mapping.get("reason") != "score-rows-not-terminal-safe":
        return False
    if not _source_model_synthesis_mapping_list(mapping, "candidates"):
        return False
    if not _source_model_synthesis_mapping_list(mapping, "score_rows"):
        return False
    profile = _source_model_synthesis_profile(function)
    if profile is None:
        return False
    return _source_model_profile_candidate_scores(
        _source_model_candidate_scores(mapping),
        profile=profile,
    )


def _is_actionable_source_model_synthesis_artifact(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if mapping.get("function") != function:
        return False
    if mapping.get("status") != "actionable":
        return False
    if _best_candidate_for_mapping(mapping) is None:
        return False
    profile = _source_model_synthesis_profile(function)
    if profile is None:
        return False
    return _source_model_profile_candidate_scores(
        _source_model_candidate_scores(mapping),
        profile=profile,
    )


def _post_meta_source_model_synthesis_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    if mapping.get("status") == "actionable":
        return _post_meta_source_model_actionable_frontier(
            mapping,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )

    score_rows = _source_model_candidate_score_rows(mapping)
    final_force = _source_model_force_from_score_rows(score_rows)
    target_anchors = _source_model_target_anchors_from_score_rows(score_rows)
    enriched = dict(mapping)
    enriched.setdefault(
        "terminal_summary",
        {
            "status": "terminal",
            "kind": "no-post-ceiling-sort-source-family",
            "terminal_blocker": "current-source-shape-ceiling",
            "terminal_reason": (
                "no-post-ceiling-sort-source-family/current-source-shape-ceiling"
            ),
            "candidate_count": len(score_rows),
            "scored_count": len(score_rows),
            "best_target_matched": 0,
            "best_target_targeted": len(final_force) or None,
            "best_target_virtual_distance": len(final_force) or None,
            "target_anchors": target_anchors,
            "final_force_phys": final_force,
            "attempted_targets": final_force,
        },
    )
    enriched.setdefault(
        "post_ceiling_final_summary",
        {
            "residual_blocker_targets": _source_model_residual_blockers_from_scores(
                score_rows,
                final_force=final_force,
            ),
        },
    )
    enriched.setdefault("_artifact_path", str(artifact))
    frontier = _post_ceiling_source_model_proof_frontier(
        enriched,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
    )
    frontier["raw_source_model_synthesis_reason"] = mapping.get("reason")
    return frontier


def _post_meta_source_model_actionable_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    score_rows = _source_model_candidate_score_rows(mapping)
    candidate_scores = _source_model_candidate_scores(mapping)
    best_candidate = _best_candidate_for_mapping(mapping)
    if best_candidate is None:
        best_candidate = {}
    final_force = _source_model_force_from_score_rows(score_rows)
    target_anchors = _source_model_target_anchors_from_score_rows(score_rows)
    if not final_force:
        final_force = _post_ceiling_force_from_target_anchors(target_anchors)
    dimension_id = _non_empty_str(best_candidate.get("dimension_id"))
    candidate_id = _non_empty_str(best_candidate.get("candidate_id"))
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        frontier_id=_frontier_id(
            function,
            _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
            ("status", "actionable"),
            ("candidate", candidate_id),
            ("dimension", dimension_id),
            ("force", final_force),
        ),
        attempted={str(key): value for key, value in final_force.items()},
        protected={},
        final_force=final_force,
        terminal=False,
    )
    frontier["suppression_family"] = _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
    continuation = _continuation(mapping, best_candidate, function)
    if isinstance(continuation, Mapping):
        continuation = dict(continuation)
        if dimension_id is not None:
            continuation.setdefault("route", dimension_id)
            continuation["dimension_id"] = dimension_id
        if candidate_id is not None:
            continuation["candidate_id"] = candidate_id
        for key in (
            "pcdump_path",
            "source_components",
            "source_hunks",
            "source_retained",
            "target_score",
            "expression_score",
        ):
            value = best_candidate.get(key)
            if value is not None:
                continuation[key] = value

    synthesis_proof = _source_model_synthesis_proof(
        mapping,
        function=function,
        final_force=final_force,
        candidate_scores=candidate_scores,
    )
    source_model_proof: dict[str, Any] = {
        "summary": "source model synthesis produced an actionable retained frontier",
        "target_anchors": target_anchors,
        "candidate_scores": candidate_scores,
        "attempted_equivalence_classes": (
            [dimension_id] if dimension_id is not None else []
        ),
    }
    if synthesis_proof is not None:
        source_model_proof["source_family_synthesis"] = synthesis_proof
        source_model_proof["attempted_equivalence_classes"] = (
            synthesis_proof["attempted_equivalence_classes"]
        )

    frontier.update({
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "actionable": continuation is not None,
        "continuation": continuation,
        "best_candidate": dict(best_candidate),
        "ranked_candidates": _source_model_ranked_candidates(mapping),
        "target_score": best_candidate.get("target_score"),
        "expression_score": best_candidate.get("expression_score"),
        "source_hunks": best_candidate.get("source_hunks"),
        "source_components": best_candidate.get("source_components"),
        "source_retained": best_candidate.get("source_retained"),
        "pcdump_path": best_candidate.get("pcdump_path"),
        "source_model_proof": source_model_proof,
        "final_force_phys": dict(final_force),
    })
    if dimension_id is not None:
        frontier["dimension_id"] = dimension_id
        frontier["source_model_layer_dimension_id"] = dimension_id
    if candidate_id is not None:
        frontier["candidate_id"] = candidate_id
    for key in (
        "candidate_count",
        "score_count",
        "joined_score_count",
        "target_matched",
        "target_targeted",
        "target_virtual_distance",
        "expression_matched",
        "expression_targeted",
        "expression_virtual_distance",
    ):
        value = mapping.get(key)
        if value is None:
            value = best_candidate.get(key)
        if value is not None:
            frontier["metrics"][key] = value
    return frontier


def _source_model_mapping_identifies_cross_tu_layer(
    mapping: Mapping[str, Any],
) -> bool:
    if (
        _non_empty_str(mapping.get("source_model_layer_dimension_id"))
        == _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
    ):
        return True

    if not _source_model_score_rows_have_required_targets(mapping):
        return False

    text = " ".join(
        str(value or "")
        for value in (
            mapping.get("output_dir"),
            mapping.get("source_retained"),
            mapping.get("source_file"),
            mapping.get("artifact"),
            mapping.get("_artifact_path"),
        )
    ).lower()
    if (
        "cross_tu_symbol_linkage" in text
        or "cross-tu-symbol-linkage" in text
        or "sort_cross_after_whole_function" in text
        or "sort-cross-after-whole-function" in text
    ):
        return True

    if _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL in set(
        _nested_strings_for_key(mapping, "next_unsupported_source_model")
    ):
        return _source_model_has_cross_tu_protected_split_evidence(mapping)

    if mapping.get("reason") != "score-rows-not-terminal-safe":
        return False
    return any(
        _nested_value(mapping, path)
        == _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
        for path in (
            ("context", "current_ceiling", "next_unsupported_source_family"),
            ("context", "next_unsupported_source_family"),
            ("current_ceiling", "next_unsupported_source_family"),
            ("next_unsupported_source_family",),
        )
    )


def _source_model_score_rows_have_required_targets(
    mapping: Mapping[str, Any],
) -> bool:
    rows = _source_model_candidate_score_rows(mapping)
    final_force = (
        _normalized_int_mapping(_nested_value(mapping, ("context", "force_phys")))
        or _normalized_int_mapping(mapping.get("force_phys"))
        or _source_model_force_from_score_rows(rows)
    )
    required = set(final_force) or {"34", "44"}
    if not {"34", "44"} <= required:
        return False
    if not rows:
        return False
    saw_required_score = False
    for row in rows:
        virtuals = _target_score_virtuals(row.get("target_score"))
        if required <= set(virtuals):
            saw_required_score = True
    return saw_required_score


def _source_model_has_cross_tu_protected_split_evidence(
    mapping: Mapping[str, Any],
) -> bool:
    rows = _source_model_candidate_score_rows(mapping)
    if not rows:
        return False
    final_force = (
        _normalized_int_mapping(_nested_value(mapping, ("context", "force_phys")))
        or _normalized_int_mapping(mapping.get("force_phys"))
        or _source_model_force_from_score_rows(rows)
        or {"34": 27, "44": 25}
    )
    summary = _source_model_cross_tu_one_hit_summary(rows, final_force)
    best_by_target = summary.get("best_by_target")
    if not isinstance(best_by_target, Mapping):
        return False
    return (
        {"34", "44"} <= set(best_by_target)
        and summary.get("protected_targets_not_jointly_preserved") is True
    )


def _normalize_cross_tu_source_model_score_row(item: dict[str, Any]) -> None:
    origin = _non_empty_str(item.get("dimension_id"))
    if origin and origin != _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION:
        item.setdefault("origin_dimension_id", origin)
    item["source_model_layer_dimension_id"] = (
        _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
    )
    item["cross_tu_symbol_linkage_source_context_model"] = True


def _source_model_raw_retained_scored_probes(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cross_tu_layer = _source_model_mapping_identifies_cross_tu_layer(mapping)
    rows: list[dict[str, Any]] = []
    for row in _source_model_candidate_score_rows(mapping):
        item = dict(row)
        if not isinstance(item.get("target_score"), Mapping):
            continue
        if cross_tu_layer:
            _normalize_cross_tu_source_model_score_row(item)
        rows.append(item)
    return rows


def _source_model_cross_tu_one_hit_summary(
    rows: Sequence[Mapping[str, Any]],
    final_force: Mapping[str, int],
) -> dict[str, Any]:
    targets = dict(final_force) or {"34": 27, "44": 25}
    one_hit_targets: dict[str, list[dict[str, Any]]] = {
        str(virtual): [] for virtual in targets
    }
    best_by_target: dict[str, dict[str, Any]] = {}
    best_joint_candidate: dict[str, Any] | None = None
    ranked_rows = sorted(rows, key=_source_model_cross_tu_score_row_rank)
    for row in ranked_rows:
        target_score = row.get("target_score")
        for virtual, expected in targets.items():
            if not _target_score_matches_virtual(target_score, virtual, expected):
                continue
            evidence = _source_model_cross_tu_score_row_evidence(row, virtual)
            one_hit_targets[str(virtual)].append(evidence)
            best_by_target.setdefault(str(virtual), evidence)
        if best_joint_candidate is None and _target_score_matches_all(
            target_score,
            targets,
        ):
            best_joint_candidate = _source_model_cross_tu_score_row_evidence(
                row,
                None,
            )
    return {
        "one_hit_targets": one_hit_targets,
        "best_by_target": best_by_target,
        "best_joint_candidate": best_joint_candidate,
        "protected_targets_not_jointly_preserved": best_joint_candidate is None,
    }


def _source_model_cross_tu_score_row_rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -(_to_int(row.get("target_matched")) or 0),
        _to_int(row.get("target_virtual_distance")) or math.inf,
        str(row.get("candidate_id") or ""),
    )


def _source_model_cross_tu_score_row_evidence(
    row: Mapping[str, Any],
    virtual: str | None,
) -> dict[str, Any]:
    evidence = {
        "candidate_id": row.get("candidate_id"),
        "source_model_layer_dimension_id": row.get(
            "source_model_layer_dimension_id"
        ),
        "origin_dimension_id": row.get("origin_dimension_id")
        or row.get("dimension_id"),
        "target_score": row.get("target_score"),
        "structural_guard": row.get("structural_guard"),
    }
    for key in (
        "source_retained",
        "source_file",
        "pcdump_path",
        "source_hunks",
        "source_components",
        "target_matched",
        "target_targeted",
        "target_virtual_distance",
    ):
        value = row.get(key)
        if value is not None:
            evidence[key] = value
    if virtual is not None:
        evidence["virtual"] = _to_int(virtual)
    return evidence


def _target_score_virtuals(target_score: Any) -> Mapping[str, Any]:
    if not isinstance(target_score, Mapping):
        return {}
    virtuals = target_score.get("virtuals")
    return virtuals if isinstance(virtuals, Mapping) else {}


def _target_score_matches_virtual(
    target_score: Any,
    virtual: str,
    expected: int,
) -> bool:
    row = _target_score_virtuals(target_score).get(str(virtual))
    if not isinstance(row, Mapping):
        return False
    actual = _register_num(row.get("actual"))
    return bool(row.get("matched")) or actual == expected


def _target_score_matches_all(
    target_score: Any,
    targets: Mapping[str, int],
) -> bool:
    return all(
        _target_score_matches_virtual(target_score, virtual, expected)
        for virtual, expected in targets.items()
    )


def _is_sort_protected_structural_recombine_artifact(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if function != _SORT_FUNCTION:
        return False
    synthesis = mapping.get("protected_structural_synthesis")
    if not isinstance(synthesis, Mapping):
        return False
    if _normalized_int_mapping(synthesis.get("required_assignments")) != (
        _SORT_PROTECTED_STRUCTURAL_TARGETS
    ):
        return False
    combinations = mapping.get("combinations")
    if not isinstance(combinations, list) or not combinations:
        return False
    return any(
        isinstance(row, Mapping)
        and row.get("status") == "ok"
        and isinstance(row.get("target_score"), Mapping)
        for row in combinations
    )


def _sort_protected_structural_recombine_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    summary = _sort_protected_structural_recombine_summary(mapping)
    final_force = dict(summary["required_assignments"])
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        frontier_id=_frontier_id(
            function,
            _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
            ("force", final_force),
            ("protected-structural-recombine", True),
        ),
        attempted=final_force,
        protected={},
        final_force=final_force,
        terminal=True,
    )
    terminal_blockers = summary["terminal_blockers"]
    protected_structural = summary["protected_structural_synthesis"]
    source_hunks_by_candidate = _source_hunks_by_candidate(
        summary["ranked_candidates"],
        dimension_id=_SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION,
    )
    synthesis = {
        "status": "synthesis-exhausted",
        "evidence_status": "artifact-protected-structural-recombine",
        "forced_target_map": dict(final_force),
        "required_assignments": dict(final_force),
        "attempted_equivalence_classes": [
            _SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION
        ],
        "exhausted_dimensions": [
            {
                "dimension_id": _SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION,
                "status": "scored-terminal",
                "exhaustion_reason": (
                    "lower-drift-candidates-lost-protected-assignments"
                ),
            }
        ],
        "candidate_scores": summary["ranked_candidates"],
        "ranked_candidates": summary["ranked_candidates"],
        "retained_scored_probes": summary["ranked_candidates"],
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "protected_structural_synthesis": protected_structural,
        "next_actions": summary["next_actions"],
        "next_unsupported_source_model": _SORT_POST_LOWER_DRIFT_UNSUPPORTED_SOURCE_MODEL,
        "next_unsupported_source_family": _SORT_FULL_SELECTION_SWAP_DIMENSION,
        "terminal_blockers": terminal_blockers,
        "terminal_blocker": summary.get("terminal_blocker"),
    }
    proof = {
        "summary": (
            "Sort protected-loss recombine evidence exhausted scored lower-drift "
            "component combinations without jointly preserving IG34/IG44."
        ),
        "register_class": "gpr",
        "candidate_scores": summary["ranked_candidates"],
        "ranked_candidates": summary["ranked_candidates"],
        "retained_scored_probes": summary["ranked_candidates"],
        "source_hunks_by_candidate": source_hunks_by_candidate,
        "source_family_synthesis": synthesis,
        "protected_structural_synthesis": protected_structural,
        "attempted_equivalence_classes": [
            _SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION
        ],
        "next_actions": summary["next_actions"],
        "next_unsupported_source_model": _SORT_POST_LOWER_DRIFT_UNSUPPORTED_SOURCE_MODEL,
        "next_unsupported_source_family": _SORT_FULL_SELECTION_SWAP_DIMENSION,
        "terminal_blockers": terminal_blockers,
        "terminal_blocker": summary.get("terminal_blocker"),
    }
    frontier["kind"] = _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_KIND
    frontier["status"] = "terminal"
    frontier["terminal_reason"] = (
        "sort-protected-loss-recombine-exhausted/"
        "protected-targets-not-jointly-preserved"
    )
    frontier["terminal_blockers"] = terminal_blockers
    frontier["terminal_blocker"] = summary.get("terminal_blocker")
    frontier["suppression_family"] = _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
    frontier["source_model_proof"] = proof
    frontier["source_family_synthesis"] = synthesis
    frontier["protected_structural_synthesis"] = protected_structural
    frontier["final_force_phys"] = dict(final_force)
    frontier["target_hits"] = _sort_protected_structural_target_hits(
        summary["ranked_candidates"],
        final_force,
    )
    frontier["protected_hits"] = dict(frontier["target_hits"])
    frontier["metrics"]["candidate_count"] = len(summary["ranked_candidates"])
    frontier["metrics"]["ok_combination_count"] = summary["ok_combination_count"]
    frontier["metrics"]["skipped_overlap_count"] = summary["skipped_overlap_count"]
    return frontier


def _sort_protected_structural_recombine_summary(
    mapping: Mapping[str, Any],
) -> dict[str, Any]:
    synthesis = mapping.get("protected_structural_synthesis")
    if not isinstance(synthesis, Mapping):
        synthesis = {}
    targets = (
        _normalized_int_mapping(synthesis.get("required_assignments"))
        or dict(_SORT_PROTECTED_STRUCTURAL_TARGETS)
    )
    combinations = [
        row for row in mapping.get("combinations") or []
        if isinstance(row, Mapping)
    ]
    ok = [row for row in combinations if row.get("status") == "ok"]
    skipped = [row for row in combinations if row.get("status") == "skipped"]
    candidates = [
        _sort_protected_structural_recombine_candidate(row, targets)
        for row in sorted(ok, key=_source_model_cross_tu_score_row_rank)
    ]
    terminal_blockers = _sort_protected_structural_terminal_blockers(
        synthesis,
        skipped=skipped,
        candidates=candidates,
        targets=targets,
    )
    protected_structural = _sort_protected_structural_payload(
        synthesis,
        required_assignments=targets,
        ranked_candidates=candidates,
        terminal_blockers=terminal_blockers,
    )
    return {
        "required_assignments": targets,
        "ranked_candidates": candidates,
        "protected_structural_synthesis": protected_structural,
        "ok_combination_count": len(ok),
        "skipped_overlap_count": len(skipped),
        "next_actions": list(synthesis.get("next_actions") or []),
        "terminal_blockers": terminal_blockers,
        "terminal_blocker": synthesis.get("terminal_blocker"),
    }


def _sort_protected_structural_recombine_candidate(
    row: Mapping[str, Any],
    targets: Mapping[str, int],
) -> dict[str, Any]:
    target_score = row.get("target_score")
    if not isinstance(target_score, Mapping):
        target_score = {}
    source_hunks = row.get("source_hunks") or row.get("applied_hunks") or []
    if not isinstance(source_hunks, list):
        source_hunks = []
    candidate = {
        "candidate_id": row.get("candidate_id"),
        "dimension_id": _SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION,
        "source_model_layer_dimension_id": (
            _SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION
        ),
        "parents": row.get("parents"),
        "status": row.get("status"),
        "target_score": target_score,
        "structural_guard": row.get("structural_guard"),
        "source_hunks": source_hunks,
        "source_retained": row.get("path")
        or _nested_value(row, ("continuation", "source_retained")),
        "pcdump_path": row.get("pcdump_path")
        or _nested_value(row, ("continuation", "pcdump_path")),
        "protected_target_results": {
            str(virtual): _target_score_matches_virtual(
                target_score,
                str(virtual),
                expected,
            )
            for virtual, expected in targets.items()
        },
    }
    for key in (
        "protected_assignments_satisfied",
        "protected_preserved_count",
        "protected_count",
        "satisfied_protected_assignments",
        "missing_protected_assignments",
        "normalized_diff_lines",
        "target_score_total",
    ):
        if row.get(key) is not None:
            candidate[key] = row[key]
    matched = _to_int(target_score.get("matched"))
    targeted = _to_int(target_score.get("targeted"))
    distance = _to_int(target_score.get("virtual_distance"))
    if matched is not None:
        candidate["target_matched"] = matched
    if targeted is not None:
        candidate["target_targeted"] = targeted
    if distance is not None:
        candidate["target_virtual_distance"] = distance
    return candidate


def _sort_protected_structural_terminal_blockers(
    synthesis: Mapping[str, Any],
    *,
    skipped: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    targets: Mapping[str, int],
) -> list[Any]:
    blockers = _list_field(synthesis.get("terminal_blockers"))
    if not blockers and not any(
        _target_score_matches_all(candidate.get("target_score"), targets)
        for candidate in candidates
    ):
        blockers.append("lower-drift-candidates-lost-protected-assignments")
    if skipped and "recombine-overlapping-source-hunks" not in blockers:
        blockers.append("recombine-overlapping-source-hunks")
    return blockers


def _sort_protected_structural_payload(
    synthesis: Mapping[str, Any],
    *,
    required_assignments: Mapping[str, int],
    ranked_candidates: Sequence[Mapping[str, Any]],
    terminal_blockers: Sequence[Any],
) -> dict[str, Any]:
    payload = dict(synthesis)
    payload["required_assignments"] = dict(required_assignments)
    payload["ranked_candidates"] = [dict(row) for row in ranked_candidates]
    payload["terminal_blockers"] = list(terminal_blockers)
    for key in (
        "lower_drift_lost_protected_candidates",
        "preserving_plateau_candidates",
    ):
        payload[key] = _sort_protected_structural_enriched_rows(
            synthesis.get(key),
            ranked_candidates=ranked_candidates,
        )
    if "next_actions" in synthesis:
        payload["next_actions"] = list(synthesis.get("next_actions") or [])
    return payload


def _sort_protected_structural_enriched_rows(
    rows: Any,
    *,
    ranked_candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    by_id = {
        row.get("candidate_id"): row
        for row in ranked_candidates
        if isinstance(row, Mapping) and row.get("candidate_id") is not None
    }
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        merged = dict(row)
        candidate = by_id.get(row.get("candidate_id"))
        if isinstance(candidate, Mapping):
            for key in (
                "dimension_id",
                "source_model_layer_dimension_id",
                "target_score",
                "structural_guard",
                "source_hunks",
                "source_retained",
                "pcdump_path",
            ):
                if merged.get(key) is None and candidate.get(key) is not None:
                    merged[key] = candidate[key]
        out.append(merged)
    return out


def _sort_protected_structural_target_hits(
    candidates: Sequence[Mapping[str, Any]],
    targets: Mapping[str, int],
) -> dict[str, bool]:
    return {
        str(virtual): any(
            _target_score_matches_virtual(
                candidate.get("target_score"),
                str(virtual),
                expected,
            )
            for candidate in candidates
        )
        for virtual, expected in targets.items()
    }


def _source_hunks_by_candidate(
    candidates: Sequence[Mapping[str, Any]],
    *,
    dimension_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        source_hunks = candidate.get("source_hunks")
        if not isinstance(source_hunks, list) or not source_hunks:
            continue
        rows.append({
            "candidate_id": candidate.get("candidate_id"),
            "dimension_id": candidate.get("dimension_id") or dimension_id,
            "source_hunks": source_hunks,
        })
    return rows


def _list_field(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if item]
    if value:
        return [value]
    return []


def _is_sort_cross_tu_recombine_artifact(
    mapping: Mapping[str, Any],
    function: str,
) -> bool:
    if function != _SORT_FUNCTION:
        return False
    if _nested_value(mapping, ("protected_structural_synthesis", "status")) == (
        "candidate-found"
    ):
        return False
    combinations = mapping.get("combinations")
    if not isinstance(combinations, list) or not combinations:
        return False
    return any(
        isinstance(row, Mapping)
        and (
            str(row.get("candidate_id") or "").startswith("combine-")
            or isinstance(row.get("parents"), list)
        )
        for row in combinations
    )


def _sort_cross_tu_recombine_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    summary = _sort_cross_tu_recombine_summary(mapping)
    if summary["joint_preserving_combination_count"]:
        return _sort_cross_tu_recombine_actionable_frontier(
            mapping,
            summary=summary,
            function=function,
            artifact=artifact,
            summary_path=summary_path,
        )
    final_force = _sort_cross_tu_recombine_force(summary) or dict(
        _SORT_INLINE_BOUNDARY_TARGETS
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        frontier_id=_frontier_id(
            function,
            _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
            ("force", final_force),
            ("cross-tu-recombine", True),
        ),
        attempted=final_force,
        protected={},
        final_force=final_force,
        terminal=True,
    )
    frontier["kind"] = _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_KIND
    frontier["terminal_reason"] = _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_REASON
    frontier["suppression_family"] = _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
    frontier["final_force_phys"] = dict(final_force)
    frontier["source_model_proof"] = {
        "summary": (
            "Sort cross-TU one-hit recombine evidence did not jointly preserve "
            "IG34/IG44."
        ),
        "register_class": "gpr",
        "candidate_scores": summary["ranked_candidates"],
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "evidence_status": "artifact-score-rows",
            "forced_target_map": dict(final_force),
            "attempted_equivalence_classes": [
                _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
            ],
            "exhausted_dimensions": [
                {
                    "dimension_id": _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
                    "status": "scored-terminal",
                    "exhaustion_reason": (
                        "one-hit-recombine-protected-targets-not-jointly-preserved"
                    ),
                }
            ],
            "recombine_negative_evidence": summary,
            "next_unsupported_source_model": (
                _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
            ),
            "next_unsupported_source_family": (
                _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
            ),
            "terminal_blockers": summary["terminal_blockers"],
        },
        "attempted_equivalence_classes": [
            _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
        ],
        "next_unsupported_source_model": (
            _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
        ),
        "next_unsupported_source_family": (
            _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
        ),
        "terminal_blockers": summary["terminal_blockers"],
    }
    return frontier


def _sort_cross_tu_recombine_actionable_frontier(
    mapping: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    candidate = summary.get("best_joint_candidate")
    if not isinstance(candidate, Mapping):
        candidate = {}
    final_force = _sort_cross_tu_recombine_force(summary) or dict(
        _SORT_INLINE_BOUNDARY_TARGETS
    )
    candidate_id = _non_empty_str(candidate.get("candidate_id")) or "cross-tu-recombine"
    source_hunks = candidate.get("source_hunks")
    if not isinstance(source_hunks, list):
        source_hunks = []
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY,
        frontier_id=_frontier_id(
            function,
            _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY,
            ("force", final_force),
            ("candidate", candidate_id),
        ),
        attempted=final_force,
        protected={},
        final_force=final_force,
        terminal=False,
    )
    score = candidate.get("target_score")
    if not isinstance(score, Mapping):
        score = {}
    frontier["kind"] = _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_KIND
    frontier["status"] = "actionable"
    frontier["suppression_family"] = (
        _POST_CEILING_SOURCE_MODEL_SEMANTIC_RECOMBINE_FAMILY
    )
    frontier["final_force_phys"] = dict(final_force)
    frontier["target_hits"] = _retained_semantic_recombine_virtual_hits(score)
    frontier["protected_hits"] = dict(frontier["target_hits"])
    frontier["metrics"] = _retained_semantic_recombine_metrics(candidate, score)
    frontier["continuation"] = {
        "route": _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
        "candidate_id": candidate_id,
        "source_hunks": source_hunks,
        "parents": candidate.get("parents"),
        "target_score": score,
        "source_retained": candidate.get("source_retained"),
    }
    frontier["actionable"] = True
    return frontier


def _sort_cross_tu_recombine_summary(mapping: Mapping[str, Any]) -> dict[str, Any]:
    combinations = [
        row for row in mapping.get("combinations") or []
        if isinstance(row, Mapping)
    ]
    ok = [row for row in combinations if row.get("status") == "ok"]
    skipped = [row for row in combinations if row.get("status") == "skipped"]
    targets = _sort_cross_tu_recombine_force_from_rows(ok) or dict(
        _SORT_INLINE_BOUNDARY_TARGETS
    )
    ranked = [
        _sort_cross_tu_recombine_candidate(row, targets)
        for row in sorted(ok, key=_source_model_cross_tu_score_row_rank)
    ]
    joint = [
        row for row in ranked
        if _target_score_matches_all(row.get("target_score"), targets)
    ]
    blockers: list[str] = []
    if not joint:
        blockers.append("one-hit-recombine-protected-targets-not-jointly-preserved")
    if skipped:
        blockers.append("recombine-overlapping-source-hunks")
    return {
        "bounded_recombine_attempted": True,
        "ok_combination_count": len(ok),
        "skipped_overlap_count": len(skipped),
        "joint_preserving_combination_count": len(joint),
        "best_joint_candidate": joint[0] if joint else None,
        "ranked_candidates": ranked,
        "skipped_combinations": [
            {
                "parents": row.get("parents"),
                "status": row.get("status"),
                "reason": row.get("reason") or row.get("skipped_reason"),
            }
            for row in skipped
        ],
        "terminal_blockers": blockers,
    }


def _sort_cross_tu_recombine_candidate(
    row: Mapping[str, Any],
    targets: Mapping[str, int],
) -> dict[str, Any]:
    target_score = row.get("target_score")
    return {
        "candidate_id": row.get("candidate_id"),
        "dimension_id": _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
        "parents": row.get("parents"),
        "status": row.get("status"),
        "target_score": target_score,
        "structural_guard": row.get("structural_guard"),
        "source_hunks": row.get("source_hunks") or row.get("applied_hunks") or [],
        "source_retained": row.get("path")
        or _nested_value(row, ("continuation", "source_retained")),
        "protected_target_results": {
            str(virtual): _target_score_matches_virtual(
                target_score,
                str(virtual),
                expected,
            )
            for virtual, expected in targets.items()
        },
    }


def _sort_cross_tu_recombine_force(summary: Mapping[str, Any]) -> dict[str, int]:
    ranked = summary.get("ranked_candidates")
    if not isinstance(ranked, list):
        return {}
    return _sort_cross_tu_recombine_force_from_rows(
        [row for row in ranked if isinstance(row, Mapping)]
    )


def _sort_cross_tu_recombine_force_from_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    for row in rows:
        force = _force_phys_from_target_score(row.get("target_score"))
        if force:
            return force
    return {}


def _source_model_force_from_score_rows(
    score_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    for row in score_rows:
        if not isinstance(row, Mapping):
            continue
        force = _force_phys_from_target_score(row.get("target_score"))
        if force:
            return force
    return {}


def _source_model_target_anchors_from_score_rows(
    score_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    for row in score_rows:
        if not isinstance(row, Mapping):
            continue
        target_score = row.get("target_score")
        if not isinstance(target_score, Mapping):
            continue
        virtuals = target_score.get("virtuals")
        if not isinstance(virtuals, Mapping):
            continue
        anchors: list[dict[str, Any]] = []
        for virtual, payload in virtuals.items():
            if not isinstance(payload, Mapping):
                continue
            parsed_virtual = _to_int(virtual)
            anchors.append({
                "virtual": parsed_virtual,
                "baseline_virtual": parsed_virtual,
                "name": f"ig{virtual}",
                "expected": _register_num(payload.get("expected")),
                "actual": _register_num(payload.get("actual")),
                "matched": bool(payload.get("matched")),
            })
        if anchors:
            return anchors
    return []


def _source_model_residual_blockers_from_scores(
    score_rows: Sequence[Mapping[str, Any]],
    *,
    final_force: Mapping[str, int],
) -> list[dict[str, Any]]:
    residual: list[dict[str, Any]] = []
    for row in score_rows:
        if not isinstance(row, Mapping):
            continue
        target_score = row.get("target_score")
        if not isinstance(target_score, Mapping):
            continue
        virtuals = target_score.get("virtuals")
        if not isinstance(virtuals, Mapping):
            continue
        for virtual, payload in virtuals.items():
            if not isinstance(payload, Mapping):
                continue
            expected = _register_num(payload.get("expected"))
            if expected is None:
                expected = final_force.get(str(virtual))
            if expected is None:
                continue
            actual = _register_num(payload.get("actual"))
            matched = bool(payload.get("matched")) or actual == expected
            if matched:
                continue
            fact = {
                "virtual": _to_int(virtual),
                "expected": expected,
                "actual": actual,
                "matched": False,
                "score_source": "target_score",
            }
            if fact not in residual:
                residual.append(fact)
    return residual


def _is_post_ceiling_source_model_proof(mapping: Mapping[str, Any]) -> bool:
    source_model_proof = mapping.get("source_model_proof")
    synthesis = (
        source_model_proof.get("source_family_synthesis")
        if isinstance(source_model_proof, Mapping)
        else None
    )
    if (
        mapping.get("status") == "terminal"
        and isinstance(source_model_proof, Mapping)
        and isinstance(synthesis, Mapping)
    ):
        return True
    summary = mapping.get("terminal_summary")
    if not isinstance(summary, Mapping):
        return False
    if not (
        isinstance(mapping.get("score_classification"), Mapping)
        or isinstance(mapping.get("evidence"), Mapping)
        or isinstance(mapping.get("post_ceiling_final_summary"), Mapping)
        or isinstance(mapping.get("source_model_proof"), Mapping)
    ):
        return False
    if summary.get("kind") not in _POST_CEILING_BASELINE_ESCAPE_KINDS:
        return False
    if (
        mapping.get("status") == "terminal"
        and isinstance(synthesis, Mapping)
        and synthesis.get("evidence_status")
        in {"artifact-synthesis-data", "artifact-score-rows"}
    ):
        return True
    if not (
        summary.get("terminal_blocker") == "current-source-shape-ceiling"
        or summary.get("terminal_reason") in _POST_CEILING_BASELINE_ESCAPE_REASONS
    ):
        return False
    target_ceiling = _zero_matched_targeted(
        summary,
        matched_key="best_target_matched",
        targeted_key="best_target_targeted",
    )
    expression_ceiling = _zero_matched_targeted(
        summary,
        matched_key="best_expression_matched",
        targeted_key="best_expression_targeted",
    )
    if not (target_ceiling or expression_ceiling):
        return False
    score_classification = mapping.get("score_classification")
    if isinstance(score_classification, Mapping):
        candidates = score_classification.get("candidates")
        if isinstance(candidates, list) and candidates:
            return True
    if isinstance(mapping.get("source_model_proof"), Mapping):
        return True
    candidates = mapping.get("candidates")
    return isinstance(candidates, list) and bool(candidates)


def _post_ceiling_source_model_proof_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    summary = mapping.get("terminal_summary")
    if not isinstance(summary, Mapping):
        summary = {}
    final_force = _normalized_force_phys(
        summary.get("final_force_phys")
        or mapping.get("final_force_phys")
        or mapping.get("attempted_targets")
        or _nested_value(mapping, ("evidence", "final_force_phys"))
        or _nested_value(mapping, ("post_ceiling_final_summary", "final_force_phys"))
    )
    target_anchors = _source_model_target_anchors(mapping)
    if not final_force:
        final_force = _post_ceiling_force_from_target_anchors(target_anchors)
    attempted = {str(key): value for key, value in final_force.items()}
    expression_anchors = _source_model_expression_anchors(mapping, target_anchors)
    candidate_scores = _source_model_candidate_scores(mapping)
    embedded_proof = (
        mapping.get("source_model_proof")
        if isinstance(mapping.get("source_model_proof"), Mapping)
        else None
    )
    if isinstance(embedded_proof, Mapping):
        if not target_anchors and isinstance(embedded_proof.get("target_anchors"), list):
            target_anchors = [
                dict(row) for row in embedded_proof["target_anchors"]
                if isinstance(row, Mapping)
            ]
        if not expression_anchors and isinstance(
            embedded_proof.get("expression_anchors"),
            list,
        ):
            expression_anchors = [
                dict(row) for row in embedded_proof["expression_anchors"]
                if isinstance(row, Mapping)
            ]
        if not candidate_scores and isinstance(
            embedded_proof.get("candidate_scores"),
            list,
        ):
            candidate_scores = [
                dict(row) for row in embedded_proof["candidate_scores"]
                if isinstance(row, Mapping)
            ]
    synthesis_proof = _source_model_synthesis_proof(
        mapping,
        function=function,
        final_force=final_force,
        candidate_scores=candidate_scores,
    )
    proof_kind, proof_reason = _source_model_proof_kind_reason(
        function=function,
        expression_anchors=expression_anchors,
        synthesis_proof=synthesis_proof,
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
        frontier_id=_frontier_id(
            function,
            _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY,
            ("force", final_force),
            ("candidates", [row.get("candidate_id") for row in candidate_scores]),
        ),
        attempted=attempted,
        protected={},
        final_force=final_force,
        terminal=True,
    )
    frontier["kind"] = proof_kind
    frontier["terminal_reason"] = proof_reason
    frontier["suppression_family"] = _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
    frontier["final_force_phys"] = dict(final_force)
    frontier["actionable"] = False
    frontier["continuation"] = None
    if summary:
        frontier["terminal_summary"] = dict(summary)
    for key in (
        "candidate_count",
        "scored_count",
        "best_expression_matched",
        "best_expression_targeted",
        "best_expression_virtual_distance",
        "best_target_matched",
        "best_target_targeted",
        "best_target_virtual_distance",
        "best_candidate_id",
    ):
        if summary.get(key) is not None:
            frontier["metrics"][key] = summary[key]
    best_target_matched = _source_model_best_target_matched(
        summary=summary,
        target_anchors=target_anchors,
        candidate_scores=candidate_scores,
    )
    best_target_targeted = _source_model_best_target_targeted(
        summary=summary,
        target_anchors=target_anchors,
        candidate_scores=candidate_scores,
    )
    best_expression_matched = _source_model_best_expression_matched(
        summary=summary,
        expression_anchors=expression_anchors,
        candidate_scores=candidate_scores,
    )
    best_expression_targeted = _source_model_best_expression_targeted(
        summary=summary,
        expression_anchors=expression_anchors,
        candidate_scores=candidate_scores,
    )
    frontier["metrics"]["best_target_matched"] = best_target_matched
    frontier["metrics"]["best_target_targeted"] = best_target_targeted
    frontier["metrics"]["best_expression_matched"] = best_expression_matched
    frontier["metrics"]["best_expression_targeted"] = best_expression_targeted
    source_model_metrics = {
        "best_target_matched": best_target_matched,
        "best_target_targeted": best_target_targeted,
        "best_expression_matched": best_expression_matched,
        "best_expression_targeted": best_expression_targeted,
    }
    source_model_proof = {
        "summary": _source_model_proof_summary(
            function=function,
            summary=summary,
            target_anchors=target_anchors,
            expression_anchors=expression_anchors,
            candidate_scores=candidate_scores,
        ),
        "suspect_source_assumption": _source_model_suspect_assumption(
            function=function,
            candidate_scores=candidate_scores,
        ),
        "register_class": _source_model_register_class(
            mapping=mapping,
            expression_anchors=expression_anchors,
        ),
        "target_anchors": target_anchors,
        "expression_anchors": expression_anchors,
        "residual_blocker_targets": _source_model_residual_blockers(mapping),
        "candidate_scores": candidate_scores,
        "metrics": source_model_metrics,
        "closed_families": _source_model_closed_families(mapping),
        "suppressed_families": _source_model_suppressed_families(mapping),
    }
    if isinstance(embedded_proof, Mapping):
        for key in (
            "residual_blocker_targets",
            "candidate_scores",
            "source_family_synthesis",
            "attempted_equivalence_classes",
            "next_unsupported_source_dimension",
            "next_unsupported_source_model",
            "next_unsupported_source_family",
            "next_unsupported_source_spans",
            "stack_clean_no_anchor_evidence",
            "post_stack_clean_no_anchor_evidence",
            "terminal_blockers",
            "unsupported_source_expression_class",
            "closed_families",
            "suppressed_families",
        ):
            value = embedded_proof.get(key)
            if value is not None and not source_model_proof.get(key):
                source_model_proof[key] = value
    if synthesis_proof is not None:
        source_model_proof["source_family_synthesis"] = synthesis_proof
        source_model_proof["attempted_equivalence_classes"] = (
            synthesis_proof["attempted_equivalence_classes"]
        )
        source_model_proof["next_unsupported_source_model"] = (
            synthesis_proof["next_unsupported_source_model"]
        )
        for key in (
            "next_unsupported_source_dimension",
            "next_unsupported_source_family",
            "next_unsupported_source_spans",
            "stack_clean_no_anchor_evidence",
            "post_stack_clean_no_anchor_evidence",
            "terminal_blockers",
        ):
            value = synthesis_proof.get(key)
            if value is not None:
                source_model_proof[key] = value
        synthesis_count = _to_int(synthesis_proof.get("candidate_count"))
        if synthesis_count is not None:
            frontier["metrics"]["source_model_synthesis_candidate_count"] = (
                synthesis_count
            )
            if synthesis_proof.get("evidence_status") in {
                "artifact-synthesis-data",
                "artifact-score-rows",
            }:
                current_count = _to_int(frontier["metrics"].get("candidate_count"))
                if current_count is None or synthesis_count > current_count:
                    frontier["metrics"]["candidate_count"] = synthesis_count
                    frontier["candidate_count"] = synthesis_count
        candidate_ids = synthesis_proof.get("all_candidate_ids")
        if isinstance(candidate_ids, list) and candidate_ids:
            frontier["candidate_ids"] = candidate_ids
    _merge_stack_clean_terminal_summary_fields(source_model_proof, summary)
    score_summary = _nested_value(
        mapping,
        ("score_classification", "terminal_summary"),
    )
    if isinstance(score_summary, Mapping):
        _merge_stack_clean_terminal_summary_fields(source_model_proof, score_summary)
    unsupported = _retained_meta_unsupported_source_expression_class(
        {"source_model_proof": source_model_proof, "function": function}
    )
    if unsupported:
        source_model_proof["unsupported_source_expression_class"] = unsupported
        frontier["unsupported_source_expression_class"] = unsupported
        if not _non_empty_str(source_model_proof.get("next_unsupported_source_model")):
            source_model_proof["next_unsupported_source_model"] = (
                _DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL
            )
    frontier["source_model_proof"] = source_model_proof
    return frontier


def _source_model_target_anchors(mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = (
        _nested_value(mapping, ("terminal_summary", "target_anchors"))
        or _nested_value(
            mapping,
            ("score_classification", "terminal_summary", "target_anchors"),
        )
        or _nested_value(mapping, ("post_ceiling_final_summary", "target_anchors"))
        or _nested_value(mapping, ("evidence", "target_anchors"))
    )
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        out.append({
            "virtual": _to_int(row.get("virtual")),
            "baseline_virtual": _to_int(row.get("baseline_virtual")),
            "name": row.get("name"),
            "expression": row.get("expression"),
            "expected": _register_num(row.get("expected")),
            "actual": _register_num(row.get("actual")),
            "matched": bool(row.get("matched")),
        })
    return out


def _source_model_candidate_scores(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    metadata_by_id = _source_model_candidate_metadata_by_id(mapping)
    score_rows = _source_model_candidate_score_rows(mapping)
    cross_tu_layer = _source_model_mapping_identifies_cross_tu_layer(mapping)
    out: list[dict[str, Any]] = []
    for row in score_rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("candidate_id") or "")
        metadata = metadata_by_id.get(candidate_id, {})
        target_score = (
            row.get("target_score")
            if isinstance(row.get("target_score"), Mapping)
            else {}
        )
        expression_score = (
            row.get("expression_score")
            if isinstance(row.get("expression_score"), Mapping)
            else {}
        )
        item = {
            "candidate_id": candidate_id,
            "dimension_id": row.get("dimension_id") or metadata.get("dimension_id"),
            "family": row.get("family") or metadata.get("family"),
            "strategy": row.get("strategy") or metadata.get("strategy"),
            "priority": row.get("priority") or metadata.get("priority"),
            "classification": row.get("classification") or metadata.get(
                "classification"
            ),
            "expression_matched": _to_int(row.get("expression_matched")),
            "expression_targeted": _to_int(row.get("expression_targeted")),
            "expression_virtual_distance": _to_int(
                row.get("expression_virtual_distance")
            ),
            "target_matched": _to_int(row.get("target_matched")),
            "target_targeted": _to_int(row.get("target_targeted")),
            "target_virtual_distance": _to_int(row.get("target_virtual_distance")),
            "expression_score": _source_model_score_summary(expression_score),
            "target_score": _source_model_score_summary(target_score),
            "expression_wrong_registers": _source_model_expression_wrong_registers(
                expression_score
            ),
            "wrong_registers": _source_model_wrong_registers(target_score),
            "spill_unexpected": target_score.get("spill_unexpected"),
            "blockers": row.get("blockers") or metadata.get("blockers"),
            "structural_guard": row.get("structural_guard")
            or metadata.get("structural_guard"),
            "artifact_reason": row.get("artifact_reason")
            or metadata.get("artifact_reason"),
            "rationale": metadata.get("rationale"),
            "expected_effect": metadata.get("expected_effect"),
            "novelty_reason": metadata.get("novelty_reason"),
            "source_hunks": row.get("source_hunks") or metadata.get(
                "source_hunks"
            ),
        }
        if cross_tu_layer:
            _normalize_cross_tu_source_model_score_row(item)
        for key in ("source_retained", "source_file", "pcdump_path"):
            value = row.get(key) or metadata.get(key)
            if value is not None:
                item[key] = value
        _classify_source_model_candidate_terminal(item)
        out.append(item)
    if out:
        return out
    for candidate_id, metadata in metadata_by_id.items():
        item = {
            "candidate_id": candidate_id,
            "dimension_id": metadata.get("dimension_id"),
            "family": metadata.get("family"),
            "strategy": metadata.get("strategy"),
            "priority": metadata.get("priority"),
            "classification": metadata.get("classification"),
            "rationale": metadata.get("rationale"),
            "expected_effect": metadata.get("expected_effect"),
            "novelty_reason": metadata.get("novelty_reason"),
            "blockers": metadata.get("blockers"),
            "structural_guard": metadata.get("structural_guard"),
            "artifact_reason": metadata.get("artifact_reason"),
            "source_hunks": metadata.get("source_hunks"),
        }
        if cross_tu_layer:
            _normalize_cross_tu_source_model_score_row(item)
        for key in ("source_retained", "source_file", "pcdump_path"):
            value = metadata.get(key)
            if value is not None:
                item[key] = value
        _classify_source_model_candidate_terminal(item)
        out.append(item)
    return out


def _source_model_candidate_metadata_by_id(
    mapping: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def merge(row: Mapping[str, Any]) -> None:
        candidate_id = _non_empty_str(row.get("candidate_id"))
        if candidate_id is None:
            return
        existing = out.setdefault(candidate_id, {})
        for key, value in row.items():
            if value is None:
                continue
            current = existing.get(key)
            if current in (None, [], {}):
                existing[key] = value

    for row in _source_model_ranked_candidates(mapping):
        merge(row)
    for row in _source_model_synthesis_mapping_list(mapping, "candidates"):
        merge(row)
    for row in _source_model_synthesis_mapping_list(mapping, "score_rows"):
        merge(row)
    for source in (
        _source_model_source_family_discovery(mapping),
        _source_model_source_family_plateau_summary(mapping),
        _source_model_source_family_progress_plateau(mapping),
    ):
        for key in (
            "probes",
            "candidates",
            "retained_scored_probes",
            "retained_candidate_inputs",
            "source_family_score_rows",
        ):
            for row in _source_model_synthesis_mapping_list(source, key):
                merge(row)
    return out


def _source_model_candidate_score_rows(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    def merge(row: Mapping[str, Any]) -> None:
        candidate_id = _non_empty_str(row.get("candidate_id"))
        if candidate_id is None:
            return
        existing = by_id.setdefault(candidate_id, {"candidate_id": candidate_id})
        for key, value in row.items():
            if value is None:
                continue
            current = existing.get(key)
            if current in (None, [], {}):
                existing[key] = value

    for row in _source_model_ranked_candidates(mapping):
        merge(row)
    for row in _source_model_synthesis_mapping_list(mapping, "score_rows"):
        if isinstance(row, Mapping):
            enriched = dict(row)
            if mapping.get("reason") is not None:
                enriched.setdefault("artifact_reason", mapping.get("reason"))
            merge(enriched)
    nested_sources: list[Mapping[str, Any]] = [mapping]
    embedded_proof = mapping.get("source_model_proof")
    if isinstance(embedded_proof, Mapping):
        nested_sources.append(embedded_proof)
    for source in list(nested_sources):
        synthesis = source.get("source_family_synthesis")
        if isinstance(synthesis, Mapping):
            nested_sources.append(synthesis)
    for source in nested_sources:
        for key in (
            "candidate_scores",
            "retained_scored_probes",
            "ranked_retained_candidates",
        ):
            for row in _source_model_synthesis_mapping_list(source, key):
                merge(row)
    score_rows = _nested_value(mapping, ("score_classification", "candidates"))
    if isinstance(score_rows, list):
        for row in score_rows:
            if isinstance(row, Mapping):
                merge(row)
    for source in (
        _source_model_source_family_plateau_summary(mapping),
        _source_model_source_family_progress_plateau(mapping),
    ):
        for row in _source_model_synthesis_mapping_list(
            source,
            "source_family_score_rows",
        ):
            merge(row)
    return list(by_id.values())


def _source_model_ranked_candidates(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    best_candidate = mapping.get("best_candidate")
    if isinstance(best_candidate, Mapping):
        rows.append(_normalized_candidate(best_candidate))
    for key in ("ranked_candidates", "risky_candidates", "ranked_retained_candidates"):
        values = mapping.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, Mapping):
                rows.append(_normalized_candidate(value))
    return rows


def _classify_source_model_candidate_terminal(item: dict[str, Any]) -> None:
    expression_score = item.get("expression_score")
    false_positive_count = (
        _to_int(expression_score.get("false_positive_virtual_id_hit_count"))
        if isinstance(expression_score, Mapping)
        else None
    )
    if (
        item.get("classification") == "target-progress"
        and false_positive_count
        and _to_int(item.get("expression_matched")) == 0
    ):
        item["terminal_classification"] = "false-positive-target-progress"
        item["terminal_reason"] = "false-positive-virtual-id-hit"
        item["actionable"] = False


def _source_model_synthesis_proof(
    mapping: Mapping[str, Any],
    *,
    function: str,
    final_force: Mapping[str, int],
    candidate_scores: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    profile = _source_model_synthesis_profile(function)
    if profile is None:
        return None

    discovery = _source_model_source_family_discovery(mapping)
    plateau_summary = _source_model_source_family_plateau_summary(mapping)
    progress_plateau = _source_model_source_family_progress_plateau(mapping)
    embedded_proof = (
        mapping.get("source_model_proof")
        if isinstance(mapping.get("source_model_proof"), Mapping)
        else None
    )
    embedded_synthesis = (
        embedded_proof.get("source_family_synthesis")
        if isinstance(embedded_proof, Mapping)
        and isinstance(embedded_proof.get("source_family_synthesis"), Mapping)
        else None
    )
    explicit_next_sources = (
        mapping,
        embedded_proof,
        embedded_synthesis,
        discovery,
        progress_plateau,
        plateau_summary,
    )
    has_artifact_data = any(
        isinstance(item, Mapping)
        for item in (discovery, plateau_summary, progress_plateau)
    )
    has_score_row_artifact = bool(
        mapping.get("reason") == "score-rows-not-terminal-safe"
        and _source_model_synthesis_mapping_list(mapping, "score_rows")
    )
    has_cross_tu_layer = _source_model_mapping_identifies_cross_tu_layer(mapping)
    has_concrete_artifact_data = has_artifact_data or has_score_row_artifact
    if not has_concrete_artifact_data and not _source_model_profile_candidate_scores(
        candidate_scores,
        profile=profile,
    ):
        return None

    dimension_details = _source_model_synthesis_dimension_details(
        discovery=discovery,
        candidate_scores=candidate_scores,
        has_artifact_data=has_concrete_artifact_data,
        profile=profile,
    )
    attempted_dimensions = [
        str(row["dimension_id"])
        for row in dimension_details
        if row.get("dimension_id")
    ]
    generated_candidate_ids = _source_model_synthesis_generated_candidate_ids(
        discovery
    )
    scored_candidate_ids = _source_model_synthesis_scored_candidate_ids(
        discovery=discovery,
        plateau_summary=plateau_summary,
        progress_plateau=progress_plateau,
        candidate_scores=candidate_scores,
    )
    prior_candidate_ids = [
        str(row.get("candidate_id"))
        for row in candidate_scores
        if row.get("candidate_id")
    ]
    all_candidate_ids = _dedupe_strings(
        [
            *prior_candidate_ids,
            *generated_candidate_ids,
            *scored_candidate_ids,
        ]
    )
    missing_dimensions = _source_model_synthesis_missing_dimensions(
        attempted_dimensions,
        has_artifact_data=has_concrete_artifact_data,
        profile=profile,
    )
    source_hunks = _source_model_synthesis_source_hunks(
        discovery=discovery,
        candidate_scores=candidate_scores,
        profile=profile,
    )
    retained_scored_probes = _source_model_synthesis_retained_scored_probes(
        discovery
    )
    if not retained_scored_probes and has_score_row_artifact:
        retained_scored_probes = _source_model_raw_retained_scored_probes(mapping)
    exhausted_dimensions = _source_model_synthesis_exhausted_dimensions(
        discovery,
        dimension_details,
    )
    one_hit_summary = (
        _source_model_cross_tu_one_hit_summary(retained_scored_probes, final_force)
        if has_cross_tu_layer
        else None
    )
    if has_cross_tu_layer:
        next_unsupported_source_model = (
            _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
        )
    else:
        next_unsupported_source_model = _source_model_first_present_field(
            "next_unsupported_source_model",
            *explicit_next_sources,
        ) or _source_model_next_unsupported_source_model(
            discovery=discovery,
            plateau_summary=plateau_summary,
            progress_plateau=progress_plateau,
            has_artifact_data=has_concrete_artifact_data,
            exhausted_dimensions=exhausted_dimensions,
            profile=profile,
        )
    proof: dict[str, Any] = {
        "status": (
            "synthesis-exhausted"
            if has_concrete_artifact_data
            else "fallback-unsupported-synthesis-model"
        ),
        "evidence_status": (
            "artifact-synthesis-data"
            if has_artifact_data
            else "artifact-score-rows"
            if has_score_row_artifact
            else "fallback-inferred-from-local-candidates"
        ),
        "forced_target_map": dict(final_force),
        "attempted_equivalence_classes": attempted_dimensions,
        "equivalence_class_details": dimension_details,
        "prior_local_candidate_ids": prior_candidate_ids,
        "generated_candidate_ids": generated_candidate_ids,
        "scored_candidate_ids": scored_candidate_ids,
        "all_candidate_ids": all_candidate_ids,
        "candidate_count": len(all_candidate_ids),
        "source_hunks_by_candidate": source_hunks,
        "retained_scored_probes": retained_scored_probes,
        "skipped_dimensions": _source_model_synthesis_mapping_list(
            discovery,
            "skipped_dimensions",
        ),
        "missing_dimensions": missing_dimensions,
        "missing_inputs": _source_model_synthesis_mapping_list(
            discovery,
            "missing_inputs",
        ),
        "exhausted_dimensions": exhausted_dimensions,
        "next_unsupported_source_model": next_unsupported_source_model,
    }
    for key in (
        "next_unsupported_source_dimension",
        "next_unsupported_source_family",
        "next_unsupported_source_spans",
        "stack_clean_no_anchor_evidence",
        "post_stack_clean_no_anchor_evidence",
        "terminal_blockers",
    ):
        value = _source_model_first_present_field(
            key,
            *explicit_next_sources,
        )
        if value is not None:
            proof[key] = value
    if has_cross_tu_layer:
        proof["next_unsupported_source_family"] = (
            _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
        )
        proof["next_unsupported_source_dimension"] = None
        blockers = list(proof.get("terminal_blockers") or [])
        if _SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER not in blockers:
            blockers.append(_SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER)
        if (
            isinstance(one_hit_summary, Mapping)
            and one_hit_summary.get("protected_targets_not_jointly_preserved")
        ):
            blocker = "one-hit-protected-targets-not-jointly-preserved"
            if blocker not in blockers:
                blockers.append(blocker)
        if blockers:
            proof["terminal_blockers"] = blockers
        if one_hit_summary:
            proof["one_hit_summary"] = one_hit_summary
    if isinstance(discovery, Mapping):
        proof["post_ceiling_source_family_discovery"] = discovery
    if isinstance(plateau_summary, Mapping):
        proof["post_ceiling_source_family_plateau_summary"] = plateau_summary
    if isinstance(progress_plateau, Mapping):
        proof["source_family_progress_plateau"] = progress_plateau
    return proof


def _retained_stack_clean_no_anchor_final_source_completed(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    if _retained_post_stack_loop_callsite_source_context_completed(raw):
        return False
    if _retained_post_stack_clean_no_anchor_source_shape_completed(raw):
        return False
    for key in (
        "terminal_reason",
        "terminal_blocker",
        "reason",
        "next_unsupported_source_model",
        "next_unsupported_source_family",
    ):
        value = _non_empty_str(raw.get(key))
        if value in {
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL,
            _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY,
        }:
            return True
    if (
        _non_empty_str(raw.get("exhausted_source_dimension"))
        == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        and raw.get("status") in {"terminal", "scored-terminal", "exhausted"}
    ):
        return True
    exhausted = raw.get("exhausted_dimensions")
    if isinstance(exhausted, Sequence) and not isinstance(exhausted, (str, bytes)):
        for row in exhausted:
            if not isinstance(row, Mapping):
                continue
            if row.get("exhaustion_reason") == (
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
            ):
                return True
            if (
                row.get("dimension_id")
                == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
                and row.get("status")
                in {"terminal", "scored-terminal", "exhausted"}
            ):
                return True
    synthesis = raw.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        return _retained_stack_clean_no_anchor_final_source_completed(synthesis)
    return False


def _retained_post_stack_clean_no_anchor_source_shape_completed(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    if _retained_post_stack_loop_callsite_source_context_completed(raw):
        return False
    for key in (
        "terminal_reason",
        "terminal_blocker",
        "reason",
        "next_unsupported_source_model",
        "next_unsupported_source_family",
    ):
        value = _non_empty_str(raw.get(key))
        if value in {
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON,
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER,
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL,
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY,
        }:
            return True
    if (
        _non_empty_str(raw.get("exhausted_source_dimension"))
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        and raw.get("status") in {"terminal", "scored-terminal", "exhausted"}
    ):
        return True
    exhausted = raw.get("exhausted_dimensions")
    if not isinstance(exhausted, Sequence) or isinstance(exhausted, (str, bytes)):
        exhausted = []
    for row in exhausted:
        if not isinstance(row, Mapping):
            continue
        if row.get("exhaustion_reason") == (
            _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
        ):
            return True
        if (
            row.get("dimension_id")
            == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
            and row.get("status") in {"terminal", "scored-terminal", "exhausted"}
        ):
            return True
    nested = raw.get("terminal_frontiers")
    if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
        if any(
            _retained_post_stack_clean_no_anchor_source_shape_completed(row)
            for row in nested
        ):
            return True
    functions = raw.get("functions")
    if isinstance(functions, Sequence) and not isinstance(functions, (str, bytes)):
        for entry in functions:
            if not isinstance(entry, Mapping):
                continue
            nested = entry.get("terminal_frontiers")
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                if any(
                    _retained_post_stack_clean_no_anchor_source_shape_completed(row)
                    for row in nested
                ):
                    return True
    embedded_proof = raw.get("source_model_proof")
    if isinstance(embedded_proof, Mapping):
        if _retained_post_stack_clean_no_anchor_source_shape_completed(embedded_proof):
            return True
    synthesis = raw.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        return _retained_post_stack_clean_no_anchor_source_shape_completed(synthesis)
    return False


def _normalize_post_row_offset_owner_expression_lifetime_terminal_proof(
    proof: dict[str, Any],
) -> None:
    proof["next_unsupported_source_family"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    )
    proof["next_unsupported_source_model"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL
    )
    proof["next_unsupported_source_dimension"] = None
    proof["terminal_reason"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
    )
    proof["terminal_blocker"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER
    )
    proof["exhausted_source_dimension"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    synthesis = proof.get("source_family_synthesis")
    evidence = proof.get("post_row_offset_owner_expression_lifetime_evidence")
    if not isinstance(evidence, Mapping) and isinstance(synthesis, Mapping):
        evidence = synthesis.get("post_row_offset_owner_expression_lifetime_evidence")
    if isinstance(evidence, Mapping):
        proof["post_row_offset_owner_expression_lifetime_evidence"] = dict(evidence)
    exhausted = list(proof.get("exhausted_dimensions") or [])
    if _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION not in {
        row.get("dimension_id") if isinstance(row, Mapping) else row
        for row in exhausted
    }:
        exhausted.append(
            {
                "dimension_id": (
                    _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
                ),
                "status": "scored-terminal",
                "exhaustion_reason": (
                    _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
                ),
            }
        )
    proof["exhausted_dimensions"] = exhausted
    if isinstance(synthesis, Mapping):
        synthesis_out = dict(synthesis)
    else:
        synthesis_out = {}
    synthesis_out["next_unsupported_source_family"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    )
    synthesis_out["next_unsupported_source_model"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL
    )
    synthesis_out["next_unsupported_source_dimension"] = None
    synthesis_out["terminal_reason"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
    )
    synthesis_out["terminal_blocker"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER
    )
    synthesis_out["exhausted_source_dimension"] = (
        _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    synthesis_out["exhausted_dimensions"] = exhausted
    if isinstance(evidence, Mapping):
        synthesis_out["post_row_offset_owner_expression_lifetime_evidence"] = dict(
            evidence
        )
    proof["source_family_synthesis"] = synthesis_out


def _retained_post_stack_loop_callsite_source_context_completed(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    for key in (
        "terminal_reason",
        "terminal_blocker",
        "reason",
        "next_unsupported_source_model",
        "next_unsupported_source_family",
    ):
        value = _non_empty_str(raw.get(key))
        if value in {
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON,
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER,
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL,
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY,
            _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL,
            _DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY,
        }:
            return True
    if (
        _non_empty_str(raw.get("exhausted_source_dimension"))
        == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        and raw.get("status") in {"terminal", "scored-terminal", "exhausted"}
    ):
        return True
    exhausted = raw.get("exhausted_dimensions")
    if not isinstance(exhausted, Sequence) or isinstance(exhausted, (str, bytes)):
        exhausted = []
    for row in exhausted:
        if not isinstance(row, Mapping):
            continue
        if row.get("exhaustion_reason") == (
            _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
        ):
            return True
        if (
            row.get("dimension_id")
            == _DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            and row.get("status") in {"terminal", "scored-terminal", "exhausted"}
        ):
            return True
    nested = raw.get("terminal_frontiers")
    if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
        if any(
            _retained_post_stack_loop_callsite_source_context_completed(row)
            for row in nested
        ):
            return True
    functions = raw.get("functions")
    if isinstance(functions, Sequence) and not isinstance(functions, (str, bytes)):
        for entry in functions:
            if not isinstance(entry, Mapping):
                continue
            nested = entry.get("terminal_frontiers")
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                if any(
                    _retained_post_stack_loop_callsite_source_context_completed(row)
                    for row in nested
                ):
                    return True
    embedded_proof = raw.get("source_model_proof")
    if isinstance(embedded_proof, Mapping):
        if _retained_post_stack_loop_callsite_source_context_completed(embedded_proof):
            return True
    synthesis = raw.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        return _retained_post_stack_loop_callsite_source_context_completed(synthesis)
    return False


def _retained_post_row_offset_owner_expression_lifetime_completed(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    for key in (
        "terminal_reason",
        "terminal_blocker",
        "reason",
        "next_unsupported_source_model",
        "next_unsupported_source_family",
    ):
        value = _non_empty_str(raw.get(key))
        if value in {
            _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON,
            _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER,
            _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_MODEL,
            _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY,
        }:
            return True
    if (
        _non_empty_str(raw.get("exhausted_source_dimension"))
        == _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    ):
        return True
    exhausted = raw.get("exhausted_dimensions")
    if not isinstance(exhausted, Sequence) or isinstance(exhausted, (str, bytes)):
        exhausted = []
    for row in exhausted:
        if not isinstance(row, Mapping):
            continue
        if row.get("exhaustion_reason") == (
            _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
        ):
            return True
        if (
            row.get("dimension_id")
            == _DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
            and row.get("status") in {"terminal", "scored-terminal", "exhausted"}
        ):
            return True
    nested = raw.get("terminal_frontiers")
    if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
        if any(
            _retained_post_row_offset_owner_expression_lifetime_completed(row)
            for row in nested
        ):
            return True
    functions = raw.get("functions")
    if isinstance(functions, Sequence) and not isinstance(functions, (str, bytes)):
        for entry in functions:
            if not isinstance(entry, Mapping):
                continue
            nested = entry.get("terminal_frontiers")
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                if any(
                    _retained_post_row_offset_owner_expression_lifetime_completed(row)
                    for row in nested
                ):
                    return True
    embedded_proof = raw.get("source_model_proof")
    if isinstance(embedded_proof, Mapping):
        if _retained_post_row_offset_owner_expression_lifetime_completed(
            embedded_proof
        ):
            return True
    synthesis = raw.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        return _retained_post_row_offset_owner_expression_lifetime_completed(synthesis)
    return False


def _source_model_first_present_field(
    key: str,
    *sources: Mapping[str, Any] | None,
) -> Any:
    for source in sources:
        if isinstance(source, Mapping) and source.get(key) is not None:
            return source[key]
    return None


def _source_model_synthesis_profile(function: str) -> dict[str, Any] | None:
    if function == _SORT_FUNCTION:
        return {
            "label": "Sort",
            "dimensions": _SORT_SOURCE_FAMILY_DIMENSIONS,
            "candidate_prefixes": (
                "post-ceiling-sort-",
                "post-ceiling-source-family-sort-",
                "post-meta-source-family-sort-",
                "post-meta-sort-natural-rewrite-",
                "post-meta-sort-full-selection-",
                "post-meta-sort-whole-function-",
                "post-meta-sort-source-context-",
                "post-meta-sort-tu-source-context-",
                "post-meta-sort-unbounded-tu-data-ownership-",
                "post-meta-sort-cross-tu-",
                "post-meta-sort-post-cross-tu-source-hypothesis-",
                "post-meta-sort-post-cross-tu-broader-natural-rewrite-",
                "post-meta-sort-post-broader-natural-inline-boundary-",
                "post-meta-sort-post-inline-boundary-selection-emission-",
            ),
            "family_prefixes": (
                "post_ceiling_sort_",
                "post-meta-source-family",
                "post_meta_source_family",
                "post-meta-sort-natural",
                "post_meta_sort_natural",
                "sort-natural",
                "sort_natural",
                "protected-loss",
                "protected_loss",
                "sort-full-selection",
                "sort_full_selection",
                "sort-whole-function",
                "sort_whole_function",
                "sort-helper-extraction",
                "sort_helper_extraction",
                "sort-data-layout",
                "sort_data_layout",
                "sort-tu-data-symbol",
                "sort_tu_data_symbol",
                "sort-helper-boundary",
                "sort_helper_boundary",
                "sort-unbounded-tu-data-ownership",
                "sort_unbounded_tu_data_ownership",
                "unbounded-tu-data-ownership",
                "unbounded_tu_data_ownership",
                "sort-cross-tu-symbol-linkage",
                "sort_cross_tu_symbol_linkage",
                "cross-tu-symbol-linkage",
                "cross_tu_symbol_linkage",
                "sort-post-cross-tu",
                "sort_post_cross_tu",
                "post_meta_sort_post_cross_tu",
                "sort-post-cross-tu-broader-natural",
                "sort_post_cross_tu_broader_natural",
                "post_meta_sort_post_cross_tu_broader_natural",
                "sort-post-broader-natural-inline-boundary",
                "sort_post_broader_natural_inline_boundary",
                "post_meta_sort_post_broader_natural_inline_boundary",
                "sort-post-inline-boundary-selection-emission",
                "sort_post_inline_boundary_selection_emission",
                "post_meta_sort_post_inline_boundary_selection_emission",
            ),
            "strategy_tokens": (
                "sort-",
                "post-meta-source-family",
                "sort-natural",
                "protected-loss",
                "full-selection",
                "full_selection",
                "whole-function",
                "whole_function",
                "helper-data-layout",
                "helper_data_layout",
                "source-context",
                "source_context",
                "cross-function",
                "cross_function",
                "tu-source-context",
                "tu_source_context",
                "tu-data-symbol",
                "tu_data_symbol",
                "helper-boundary",
                "helper_boundary",
                "unbounded-tu-data-ownership",
                "unbounded_tu_data_ownership",
                "whole-tu-data",
                "whole_tu_data",
                "nonlocal-source-ownership",
                "nonlocal_source_ownership",
                "cross-tu",
                "cross_tu",
                "symbol-linkage",
                "symbol_linkage",
                "data-section-ownership",
                "data_section_ownership",
                "broader-natural",
                "broader_natural",
                "natural-c-rewrite",
                "natural_c_rewrite",
                "post-broader-natural",
                "post_broader_natural",
                "inline-boundary",
                "inline_boundary",
                "post-inline-boundary",
                "post_inline_boundary",
                "selection-emission",
                "selection_emission",
            ),
            "post_lower_drift_next_unsupported": (
                _SORT_POST_LOWER_DRIFT_UNSUPPORTED_SOURCE_MODEL
            ),
            "artifact_next_unsupported": (
                "No bounded source-family proof data around the retained Sort "
                "initialization loop, indexed byte reads, call-return copy locals, "
                "or selected-slot lvalue materialization moved IG34/IG44 onto the "
                "forced registers. The next unsupported source model is the full "
                "transform-corpus adapter for broader Sort source-model synthesis, "
                "or an alternate natural C sort structure outside the current "
                "retained baseline assumptions."
            ),
            "fallback_next_unsupported": (
                "This #981-era artifact has no source-family discovery or plateau "
                "data; only the retained Sort local source-model candidates were "
                "scored. The next unsupported source model is a broader Sort "
                "source-family synthesis pass, including the transform-corpus "
                "adapter for initialization, indexed byte cache, call-return "
                "copy-local, and selected-slot lvalue equivalence classes outside "
                "the current retained baseline assumptions."
            ),
        }
    if function == _DRAW_FUNCTION:
        return {
            "label": "Draw",
            "dimensions": _DRAW_SOURCE_FAMILY_DIMENSIONS
            + (
                _DRAW_COUPLED_FPR_LIFETIME_DIMENSION,
                _DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_DIMENSION,
                _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION,
                _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION,
            ),
            "optional_dimensions": (
                _DRAW_COUPLED_FPR_LIFETIME_DIMENSION,
                _DRAW_ALTERNATE_FPR_EXPRESSION_STRUCTURE_DIMENSION,
                _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION,
                _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
                _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
                _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION,
            ),
            "candidate_prefixes": (
                "post-ceiling-paired-",
                "post-ceiling-digit-",
                "post-ceiling-source-family-draw-",
                "draw-post-all-known-frontiers-source-context-hypothesis-",
                "draw-post-all-known-product-translate-graph-",
                "draw-post-product-translate-stack-clean-no-anchor-",
                "draw-post-stack-clean-no-anchor-shape-",
            ),
            "family_prefixes": (
                "post_ceiling_statement_grouping",
                "post_ceiling_paired_owner_baseline",
                "post_ceiling_call_temp_materialization",
                "post_ceiling_source_family_draw_",
                "draw-post-all-known-frontiers-source-context-hypothesis",
                "draw_post_all_known_frontiers_source_context_hypothesis",
                "draw-post-all-known-loop-product-translate-expression-graph",
                "draw_post_all_known_loop_product_translate_expression_graph",
                "draw-post-product-translate-stack-clean-no-anchor-recovery",
                "draw_post_product_translate_stack_clean_no_anchor_recovery",
                "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis",
                "draw_post_stack_clean_no_anchor_fpr_source_shape_hypothesis",
                "draw-post-stack-clean-no-anchor-shape",
                "draw_post_stack_clean_no_anchor_shape",
            ),
            "strategy_tokens": (
                "paired-offset",
                "paired-visible",
                "digit-anim",
                "draw-",
                "col-offset",
                "row-offset",
                "callarg",
                "fsubs",
                "post-all-known",
                "post_all_known",
                "product-translate",
                "product_translate",
                "translate-graph",
                "translate_graph",
                "stack-clean",
                "stack_clean",
                "no-anchor",
                "no_anchor",
                "post-stack-clean",
                "post_stack_clean",
                "source-shape",
                "source_shape",
                "declaration-packing",
                "digit-base",
                "frame-neutral",
            ),
            "artifact_next_unsupported": (
                "No bounded source-family proof data around DrawCellNumber's "
                "column cast/product local, row translation/scale split, or "
                "digit callarg/fsubs temp moved IG32/IG37/IG46 onto the forced "
                "FPRs. The next unsupported source model is a broader Draw FPR "
                "expression synthesis pass outside the retained baseline "
                "row/column and digit-animation source assumptions."
            ),
            "fallback_next_unsupported": (
                "This #980-era artifact has no source-family discovery or plateau "
                "data; only the retained Draw expression source-model candidates "
                "were scored. The next unsupported source model is a broader Draw "
                "FPR expression source-family synthesis pass covering column "
                "cast/product locals, row translation/scale splits, and digit "
                "callarg/fsubs temp materialization outside the current retained "
                "baseline assumptions."
            ),
        }
    return None


def _source_model_source_family_discovery(
    mapping: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for value in (
        mapping.get("post_ceiling_source_family_discovery"),
        _nested_value(
            mapping,
            ("post_ceiling_final_summary", "post_ceiling_source_family_discovery"),
        ),
    ):
        if isinstance(value, Mapping):
            return value
    return None


def _source_model_source_family_plateau_summary(
    mapping: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    value = mapping.get("post_ceiling_source_family_plateau_summary")
    return value if isinstance(value, Mapping) else None


def _source_model_source_family_progress_plateau(
    mapping: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for value in (
        _nested_value(mapping, ("terminal_summary", "source_family_progress_plateau")),
        _nested_value(
            mapping,
            (
                "score_classification",
                "terminal_summary",
                "source_family_progress_plateau",
            ),
        ),
    ):
        if isinstance(value, Mapping):
            return value
    return None


def _source_model_profile_candidate_scores(
    candidate_scores: Sequence[Mapping[str, Any]],
    *,
    profile: Mapping[str, Any],
) -> bool:
    for row in candidate_scores:
        family = str(row.get("family") or "")
        candidate_id = str(row.get("candidate_id") or "")
        strategy = str(row.get("strategy") or "")
        if any(
            candidate_id.startswith(prefix)
            for prefix in _string_items(profile.get("candidate_prefixes"))
        ):
            return True
        if any(
            family.startswith(prefix)
            for prefix in _string_items(profile.get("family_prefixes"))
        ):
            return True
        if any(
            token in strategy
            for token in _string_items(profile.get("strategy_tokens"))
        ):
            return True
        if _explicit_or_fallback_source_model_dimensions(row, profile=profile):
            return True
    return False


def _source_model_synthesis_dimension_details(
    *,
    discovery: Mapping[str, Any] | None,
    candidate_scores: Sequence[Mapping[str, Any]],
    has_artifact_data: bool,
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_dimension: dict[str, dict[str, Any]] = {}
    if isinstance(discovery, Mapping):
        for key in (
            "source_family_dimensions",
            "generated_family_dimensions",
            "exhausted_dimensions",
        ):
            for row in _source_model_synthesis_mapping_list(discovery, key):
                if not _source_model_dimension_row_has_evidence(row):
                    continue
                dimension_id = _source_model_synthesis_dimension_id(row)
                if dimension_id is None:
                    continue
                existing = by_dimension.setdefault(dimension_id, {})
                existing.update(row)
                existing["dimension_id"] = dimension_id

        for key in ("probes", "candidates", "retained_scored_probes"):
            for row in _source_model_synthesis_mapping_list(discovery, key):
                dimension_id = _source_model_synthesis_dimension_id(row)
                if dimension_id is None:
                    dimension_id = _dimension_from_candidate_id(
                        _non_empty_str(row.get("candidate_id"))
                        or _non_empty_str(row.get("probe_id"))
                    )
                if dimension_id is None:
                    continue
                existing = by_dimension.setdefault(dimension_id, {
                    "dimension_id": dimension_id,
                })
                candidate_id = _non_empty_str(row.get("candidate_id"))
                if candidate_id is not None:
                    ids = list(existing.get("candidate_ids") or [])
                    if candidate_id not in ids:
                        ids.append(candidate_id)
                    existing["candidate_ids"] = ids

    if not by_dimension:
        for row in candidate_scores:
            dimensions = _explicit_or_fallback_source_model_dimensions(
                row,
                profile=profile,
            )
            for dimension_id in dimensions:
                existing = by_dimension.setdefault(dimension_id, {
                    "dimension_id": dimension_id,
                    "status": _source_model_dimension_status(row),
                    "exhaustion_reason": _source_model_dimension_exhaustion_reason(row),
                })
                candidate_id = _non_empty_str(row.get("candidate_id"))
                if candidate_id is not None:
                    ids = list(existing.get("candidate_ids") or [])
                    if candidate_id not in ids:
                        ids.append(candidate_id)
                    existing["candidate_ids"] = ids
                family = _non_empty_str(row.get("family"))
                if family is not None:
                    existing.setdefault("families", [])
                    if family not in existing["families"]:
                        existing["families"].append(family)
                blockers = row.get("blockers")
                if isinstance(blockers, list) and blockers:
                    existing.setdefault("blockers", [])
                    for blocker in blockers:
                        if blocker not in existing["blockers"]:
                            existing["blockers"].append(blocker)

    if not has_artifact_data:
        for row in by_dimension.values():
            row.setdefault("status", "fallback-inferred")
            row.setdefault(
                "exhaustion_reason",
                "source-family-discovery-data-absent",
            )

    return [
        by_dimension[key]
        for key in sorted(
            by_dimension,
            key=lambda value: _source_model_dimension_sort_key(value, profile),
        )
    ]


def _source_model_synthesis_dimension_id(row: Mapping[str, Any]) -> str | None:
    for key in ("dimension_id", "equivalence_class", "source_family_dimension"):
        value = _non_empty_str(row.get(key))
        if value is not None:
            return value
    return None


def _source_model_dimension_row_has_evidence(row: Mapping[str, Any]) -> bool:
    for key in ("candidate_count", "scored_count"):
        if _to_int(row.get(key)):
            return True
    for key in (
        "generated_candidate_ids",
        "scored_candidate_ids",
        "candidate_ids",
        "blockers",
    ):
        value = row.get(key)
        if isinstance(value, list) and value:
            return True
    return any(
        _non_empty_str(row.get(key)) is not None
        for key in ("status", "exhaustion_reason", "reason")
    )


def _source_model_dimension_sort_key(
    value: str,
    profile: Mapping[str, Any],
) -> tuple[int, str]:
    dimensions = tuple(_string_items(profile.get("dimensions")))
    try:
        return (dimensions.index(value), value)
    except ValueError:
        return (len(dimensions), value)


def _fallback_source_model_dimensions(
    row: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
) -> list[str]:
    label = str(profile.get("label") or "")
    values = " ".join(
        str(row.get(key) or "")
        for key in ("candidate_id", "family", "strategy", "rationale")
    ).lower()
    out: list[str] = []
    if label == "Sort":
        if (
            "sort-protected-loss-init-lifetime" in values
            or "protected-loss" in values
            or "init-lifetime" in values
        ):
            out.append("sort-protected-loss-init-lifetime")
        if "indexed-byte" in values or "byte-cache" in values:
            out.append("sort-indexed-byte-cache")
        if "call-return" in values or "copy-local" in values:
            out.append("sort-call-return-copy-local")
        if "swap" in values or "selected-slot" in values or "slot" in values:
            out.append("sort-swap-slot-lvalue")
        if "init" in values or "pointer-walk" in values or "loop-shape" in values:
            out.append("sort-init-indexed-write")
        if (
            "full-selection" in values
            or "full_selection" in values
            or "selection/swap" in values
        ):
            out.append(_SORT_FULL_SELECTION_SWAP_DIMENSION)
        if (
            "whole-function" in values
            or "whole_function" in values
            or "control/data-flow" in values
            or "control-data-flow" in values
        ):
            out.append(_SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION)
        if (
            "post-inline-boundary" in values
            or "post_inline_boundary" in values
            or "selection-emission" in values
            or "selection_emission" in values
        ):
            out.append(
                _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
            )
        if (
            "post-broader-natural" in values
            or "post_broader_natural" in values
            or "inline-boundary" in values
            or "inline_boundary" in values
        ) and (
            _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
            not in out
        ):
            out.append(
                _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
            )
        if not (
            _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
            in out
        ) and (
            "broader-natural" in values
            or "broader_natural" in values
            or "natural-c-rewrite" in values
            or "natural_c_rewrite" in values
        ):
            out.append(_SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION)
        if (
            "unbounded-tu-data-ownership" in values
            or "unbounded_tu_data_ownership" in values
            or "whole-tu-data" in values
            or "whole_tu_data" in values
            or "nonlocal-source-ownership" in values
            or "nonlocal_source_ownership" in values
        ):
            out.append(_SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION)
        if (
            "tu-source-context" in values
            or "tu_source_context" in values
            or "tu-data-symbol" in values
            or "tu_data_symbol" in values
            or "helper-boundary" in values
            or "helper_boundary" in values
        ):
            out.append(_SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION)
    elif label == "Draw":
        paired = (
            "paired-offset" in values
            or "paired-visible" in values
            or "statement_grouping" in values
            or "paired_owner" in values
            or "row/column" in values
            or "row-column" in values
        )
        if (
            paired
            or "col-offset" in values
            or "col_" in values
            or " column " in values
        ):
            out.append("draw-col-cast-product-local")
        if (
            paired
            or "row-offset" in values
            or "row_" in values
            or "translation" in values
            or "scale" in values
            or " row " in values
        ):
            out.append("draw-row-translation-scale-split")
        if "digit" in values or "callarg" in values or "fsubs" in values:
            out.append("draw-digit-callarg-fsubs-temp")
        if (
            "post-stack-clean" in values
            or "post_stack_clean" in values
            or "source-shape" in values
            or "source_shape" in values
            or "declaration-packing" in values
            or "digit-base" in values
            or "frame-neutral" in values
        ):
            out.append(_DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION)
    dimensions = set(_string_items(profile.get("dimensions")))
    return [dimension for dimension in _dedupe_strings(out) if dimension in dimensions]


def _explicit_or_fallback_source_model_dimensions(
    row: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
) -> list[str]:
    dimensions = set(_string_items(profile.get("dimensions")))
    explicit = _source_model_synthesis_dimension_id(row)
    out: list[str] = []
    layer = _non_empty_str(row.get("source_model_layer_dimension_id"))
    if layer in dimensions:
        out.append(str(layer))
    if explicit in dimensions:
        out.append(str(explicit))
    candidate_dimension = _dimension_from_candidate_id(
        _non_empty_str(row.get("candidate_id"))
    )
    if candidate_dimension in dimensions:
        out.append(str(candidate_dimension))
    out.extend(_fallback_source_model_dimensions(row, profile=profile))
    return [dimension for dimension in _dedupe_strings(out) if dimension in dimensions]


def _source_model_dimension_status(row: Mapping[str, Any]) -> str:
    if row.get("artifact_reason") == "score-rows-not-terminal-safe":
        return "artifact-score-rows"
    return "fallback-inferred"


def _source_model_dimension_exhaustion_reason(row: Mapping[str, Any]) -> str:
    blockers = row.get("blockers")
    if isinstance(blockers, list) and blockers:
        if "protected-targets-not-jointly-preserved" in blockers:
            return "protected-targets-not-jointly-preserved"
        return ",".join(str(blocker) for blocker in blockers if blocker)
    if row.get("artifact_reason") == "score-rows-not-terminal-safe":
        return "score-rows-not-terminal-safe"
    return "source-family-discovery-data-absent"


def _dimension_from_candidate_id(candidate_id: str | None) -> str | None:
    if not candidate_id:
        return None
    if candidate_id.startswith(
        "draw-post-all-known-frontiers-source-context-hypothesis-"
    ):
        return _DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
    if candidate_id.startswith("draw-post-all-known-product-translate-graph-"):
        return _DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION
    if candidate_id.startswith("draw-post-stack-clean-no-anchor-shape-"):
        return _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    if candidate_id.startswith(
        "draw-post-product-translate-stack-clean-no-anchor-"
    ):
        return _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    prefix = "post-ceiling-source-family-"
    if candidate_id.startswith(prefix):
        return candidate_id[len(prefix):]
    if candidate_id.startswith("post-meta-source-family-sort-swap-slot-lvalue-"):
        return _SORT_SWAP_SLOT_LVALUE_DIMENSION
    if candidate_id.startswith("post-meta-sort-semantic-recombine-"):
        return _SORT_SEMANTIC_RECOMBINE_DIMENSION
    if candidate_id.startswith("post-meta-sort-full-selection-"):
        return _SORT_FULL_SELECTION_SWAP_DIMENSION
    if candidate_id.startswith("post-meta-sort-whole-function-"):
        return _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    if candidate_id.startswith("post-meta-sort-source-context-"):
        return _SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
    if candidate_id.startswith("post-meta-sort-tu-source-context-"):
        return _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
    if candidate_id.startswith("post-meta-sort-unbounded-tu-data-ownership-"):
        return _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
    if candidate_id.startswith("post-meta-sort-post-cross-tu-broader-natural-rewrite-"):
        return _SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
    if candidate_id.startswith(
        "post-meta-sort-post-inline-boundary-selection-emission-"
    ):
        return _SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
    if candidate_id.startswith("post-meta-sort-post-broader-natural-inline-boundary-"):
        return _SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
    if candidate_id.startswith("post-meta-sort-post-cross-tu-source-hypothesis-"):
        return _SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION
    return None


def _source_model_synthesis_generated_candidate_ids(
    discovery: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(discovery, Mapping):
        return []
    ids: list[str] = []
    for row in _source_model_synthesis_dimension_rows(discovery):
        ids.extend(_string_items(row.get("generated_candidate_ids")))
    for key in ("probes", "candidates"):
        for row in _source_model_synthesis_mapping_list(discovery, key):
            ids.append(
                _non_empty_str(row.get("candidate_id"))
                or _non_empty_str(row.get("probe_id"))
                or ""
            )
    return _dedupe_strings(ids)


def _source_model_synthesis_scored_candidate_ids(
    *,
    discovery: Mapping[str, Any] | None,
    plateau_summary: Mapping[str, Any] | None,
    progress_plateau: Mapping[str, Any] | None,
    candidate_scores: Sequence[Mapping[str, Any]],
) -> list[str]:
    ids: list[str] = []
    for row in _source_model_synthesis_dimension_rows(discovery):
        ids.extend(_string_items(row.get("scored_candidate_ids")))
    for source in (discovery, plateau_summary, progress_plateau):
        if not isinstance(source, Mapping):
            continue
        ids.extend(_string_items(source.get("source_family_candidate_ids")))
        ids.extend(_string_items(source.get("progress_candidate_ids")))
        for key in ("source_family_score_rows", "retained_scored_probes"):
            for row in _source_model_synthesis_mapping_list(source, key):
                ids.append(_non_empty_str(row.get("candidate_id")) or "")
    for row in candidate_scores:
        ids.append(_non_empty_str(row.get("candidate_id")) or "")
    return _dedupe_strings(ids)


def _source_model_synthesis_dimension_rows(
    discovery: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(discovery, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for key in (
        "source_family_dimensions",
        "generated_family_dimensions",
        "exhausted_dimensions",
    ):
        rows.extend(_source_model_synthesis_mapping_list(discovery, key))
    return rows


def _source_model_synthesis_missing_dimensions(
    attempted_dimensions: Sequence[str],
    *,
    has_artifact_data: bool,
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    attempted = set(attempted_dimensions)
    optional = set(_string_items(profile.get("optional_dimensions")))
    reason = (
        "not-present-in-source-family-artifact"
        if has_artifact_data
        else "source-family-discovery-data-absent"
    )
    return [
        {
            "dimension_id": dimension,
            "status": "missing",
            "reason": reason,
        }
        for dimension in _string_items(profile.get("dimensions"))
        if dimension not in attempted
        and dimension not in optional
        and (
            has_artifact_data
            or dimension not in _SORT_FALLBACK_DEFERRED_SOURCE_FAMILY_DIMENSIONS
        )
    ]


def _source_model_synthesis_source_hunks(
    *,
    discovery: Mapping[str, Any] | None,
    candidate_scores: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(discovery, Mapping):
        for key in ("probes", "candidates", "retained_scored_probes"):
            for row in _source_model_synthesis_mapping_list(discovery, key):
                source_hunks = row.get("source_hunks")
                if not isinstance(source_hunks, list) or not source_hunks:
                    continue
                rows.append({
                    "candidate_id": row.get("candidate_id") or row.get("probe_id"),
                    "dimension_id": (
                        _source_model_synthesis_dimension_id(row)
                        or _dimension_from_candidate_id(
                            _non_empty_str(row.get("candidate_id"))
                            or _non_empty_str(row.get("probe_id"))
                        )
                    ),
                    "source_hunks": source_hunks,
                })
    for row in candidate_scores:
        source_hunks = row.get("source_hunks")
        if not isinstance(source_hunks, list) or not source_hunks:
            continue
        dimensions = _explicit_or_fallback_source_model_dimensions(row, profile=profile)
        item = {
            "candidate_id": row.get("candidate_id"),
            "source_hunks": source_hunks,
        }
        if dimensions:
            item["dimension_id"] = dimensions[0]
            item["dimension_ids"] = dimensions
        rows.append({
            **item,
        })
    return rows


def _source_model_synthesis_retained_scored_probes(
    discovery: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(discovery, Mapping):
        return []
    retained = _source_model_synthesis_mapping_list(
        discovery,
        "retained_scored_probes",
    )
    if retained:
        return retained
    return _source_model_synthesis_mapping_list(
        discovery,
        "retained_candidate_inputs",
    )


def _source_model_synthesis_exhausted_dimensions(
    discovery: Mapping[str, Any] | None,
    dimension_details: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = _source_model_synthesis_mapping_list(discovery, "exhausted_dimensions")
    if rows:
        return rows
    return [
        dict(row)
        for row in dimension_details
        if row.get("status") in {"scored-terminal", "fallback-inferred"}
        or row.get("exhaustion_reason")
    ]


def _source_model_synthesis_mapping_list(
    mapping: Mapping[str, Any] | None,
    key: str,
) -> list[dict[str, Any]]:
    if not isinstance(mapping, Mapping):
        return []
    value = mapping.get(key)
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _source_model_next_unsupported_source_model(
    *,
    discovery: Mapping[str, Any] | None,
    plateau_summary: Mapping[str, Any] | None,
    progress_plateau: Mapping[str, Any] | None,
    has_artifact_data: bool,
    exhausted_dimensions: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
) -> str:
    exhausted_ids = {
        str(row.get("dimension_id"))
        for row in exhausted_dimensions
        if isinstance(row, Mapping) and row.get("dimension_id")
    }
    for source in (discovery, progress_plateau, plateau_summary):
        if not isinstance(source, Mapping):
            continue
        value = _non_empty_str(source.get("next_unsupported_source_model"))
        if value is not None:
            return value
    if _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION in exhausted_ids:
        return _SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
    if _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION in exhausted_ids:
        return _SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_MODEL
    if _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION in exhausted_ids:
        return _SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL
    if _SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION in exhausted_ids:
        return _SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL
    if _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION in exhausted_ids:
        return _SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL
    if _SORT_FULL_SELECTION_SWAP_DIMENSION in exhausted_ids:
        return _SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL
    if "sort-protected-loss-init-lifetime" in exhausted_ids:
        value = _non_empty_str(profile.get("post_lower_drift_next_unsupported"))
        if value is not None:
            return value
    if has_artifact_data:
        return str(profile["artifact_next_unsupported"])
    return str(profile["fallback_next_unsupported"])


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _zero_matched_targeted(
    mapping: Mapping[str, Any],
    *,
    matched_key: str,
    targeted_key: str,
) -> bool:
    matched = _to_int(mapping.get(matched_key))
    targeted = _to_int(mapping.get(targeted_key))
    return matched == 0 and targeted not in (None, 0)


def _source_model_proof_kind_reason(
    *,
    function: str,
    expression_anchors: Sequence[Mapping[str, Any]],
    synthesis_proof: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    if (
        isinstance(synthesis_proof, Mapping)
        and synthesis_proof.get("evidence_status")
        in {"artifact-synthesis-data", "artifact-score-rows"}
    ):
        if expression_anchors and function == _DRAW_FUNCTION:
            return (
                _POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_SYNTHESIS_PROOF_KIND,
                _POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_SYNTHESIS_PROOF_REASON,
            )
        return (
            _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_KIND,
            _POST_CEILING_GPR_SOURCE_MODEL_SYNTHESIS_PROOF_REASON,
        )
    if expression_anchors:
        return (
            _POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_PROOF_KIND,
            _POST_CEILING_FPR_EXPRESSION_SOURCE_MODEL_PROOF_REASON,
        )
    return (
        _POST_CEILING_GPR_SOURCE_MODEL_PROOF_KIND,
        _POST_CEILING_GPR_SOURCE_MODEL_PROOF_REASON,
    )


def _source_model_expression_anchors(
    mapping: Mapping[str, Any],
    target_anchors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_virtual: dict[int, dict[str, Any]] = {}
    proof_anchors = _nested_value(mapping, ("source_model_proof", "expression_anchors"))
    if isinstance(proof_anchors, list):
        for row in proof_anchors:
            if not isinstance(row, Mapping):
                continue
            virtual = _to_int(row.get("virtual"))
            if virtual is None:
                continue
            by_virtual[virtual] = dict(row)
    for anchor in target_anchors:
        virtual = _to_int(anchor.get("virtual"))
        if virtual is None:
            continue
        if anchor.get("expression") or anchor.get("name"):
            by_virtual.setdefault(virtual, {
                "virtual": virtual,
                "baseline_virtual": _to_int(anchor.get("baseline_virtual")),
                "name": anchor.get("name"),
                "expression": anchor.get("expression"),
                "expected": _register_num(anchor.get("expected")),
                "actual": _register_num(anchor.get("actual")),
                "matched": bool(anchor.get("matched")),
            })

    score_rows = _nested_value(mapping, ("score_classification", "candidates"))
    if not isinstance(score_rows, list):
        score_rows = []
    for row in score_rows:
        if not isinstance(row, Mapping):
            continue
        expression_score = row.get("expression_score")
        if not isinstance(expression_score, Mapping):
            continue
        register_class = _non_empty_str(expression_score.get("register_class"))
        if register_class is not None and register_class != "fpr":
            continue
        virtuals = expression_score.get("virtuals")
        if not isinstance(virtuals, Mapping):
            continue
        for raw_virtual, score_row in virtuals.items():
            if not isinstance(score_row, Mapping):
                continue
            virtual = _to_int(raw_virtual)
            if virtual is None:
                continue
            anchor = by_virtual.setdefault(virtual, {"virtual": virtual})
            baseline_source = _source_model_source_span(
                score_row.get("baseline_source")
            )
            signature = score_row.get("signature")
            if isinstance(signature, Mapping):
                anchor.setdefault("name", signature.get("name"))
                anchor.setdefault("expression", signature.get("expression"))
                anchor.setdefault("source_kind", signature.get("source_kind"))
            if baseline_source:
                anchor.setdefault("name", baseline_source.get("name"))
                anchor.setdefault("expression", baseline_source.get("expression"))
                anchor["baseline_source"] = baseline_source
            anchor.setdefault(
                "baseline_virtual",
                _to_int(score_row.get("baseline_virtual")),
            )
            anchor.setdefault("expected", _register_num(score_row.get("expected")))
            anchor.setdefault("actual", _register_num(score_row.get("actual")))
            anchor.setdefault("matched", bool(score_row.get("matched")))

    return [
        by_virtual[key]
        for key in sorted(by_virtual)
        if by_virtual[key].get("expression") or by_virtual[key].get("baseline_source")
    ]


def _source_model_score_summary(score: Any) -> dict[str, Any]:
    if not isinstance(score, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "register_class",
        "derived_from_baseline",
        "matched",
        "targeted",
        "virtual_distance",
        "renumbered",
        "false_positive_virtual_id_hit_count",
        "spill_unexpected",
        "spill_missing",
    ):
        if score.get(key) is not None:
            out[key] = score[key]
    return out


def _source_model_expression_wrong_registers(
    expression_score: Any,
) -> list[dict[str, Any]]:
    if not isinstance(expression_score, Mapping):
        return []
    virtuals = expression_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for raw_virtual, row in virtuals.items():
        if not isinstance(row, Mapping):
            continue
        if row.get("matched") is True or row.get("virtual_id_matched") is True:
            continue
        signature = row.get("signature")
        if not isinstance(signature, Mapping):
            signature = {}
        baseline_source = _source_model_source_span(row.get("baseline_source"))
        candidate_source = _source_model_source_span(row.get("candidate_source"))
        out.append({
            "virtual": _to_int(raw_virtual),
            "baseline_virtual": _to_int(row.get("baseline_virtual")),
            "name": signature.get("name") or baseline_source.get("name"),
            "expression": (
                signature.get("expression")
                or baseline_source.get("expression")
                or candidate_source.get("expression")
            ),
            "expected": _register_num(row.get("expected")),
            "actual": _register_num(row.get("actual")),
            "virtual_id_actual": _register_num(row.get("virtual_id_actual")),
            "candidate_virtual": _to_int(row.get("candidate_virtual")),
            "renumbered": bool(row.get("renumbered")),
            "baseline_source": baseline_source,
            "candidate_source": candidate_source,
        })
    return out


def _source_model_source_span(source: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "kind",
        "confidence",
        "name",
        "type",
        "source_file",
        "source_line",
        "source_col",
        "expression",
        "first_def",
    ):
        if source.get(key) is not None:
            out[key] = source[key]
    return out


def _source_model_wrong_registers(target_score: Any) -> list[dict[str, Any]]:
    if not isinstance(target_score, Mapping):
        return []
    wrong = target_score.get("wrong")
    if isinstance(wrong, list) and wrong:
        return [
            {
                "virtual": _to_int(row.get("virtual")),
                "expected": _register_num(row.get("expected")),
                "actual": _register_num(row.get("actual")),
            }
            for row in wrong
            if isinstance(row, Mapping)
        ]
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for raw_virtual, row in virtuals.items():
        if not isinstance(row, Mapping):
            continue
        if row.get("matched") is True or row.get("hit") is True:
            continue
        out.append({
            "virtual": _to_int(raw_virtual),
            "expected": _register_num(row.get("expected")),
            "actual": _register_num(row.get("actual")),
        })
    return out


def _source_model_residual_blockers(
    mapping: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = None
    for path in (
        ("source_model_proof", "residual_blocker_targets"),
        ("terminal_summary", "residual_blocker_targets"),
        ("post_ceiling_final_summary", "residual_blocker_targets"),
    ):
        value = _nested_value(mapping, path)
        if isinstance(value, list):
            raw = value
            break
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        blocker = {
            "virtual": _to_int(row.get("virtual")),
            "expected": _register_num(row.get("expected")),
            "actual": _register_num(row.get("actual")),
            "score_source": row.get("score_source"),
        }
        for key in ("name", "expression", "baseline_source"):
            if row.get(key) is not None:
                blocker[key] = row[key]
        out.append(blocker)
    return out


def _source_model_closed_families(mapping: Mapping[str, Any]) -> list[str]:
    closed = _nested_value(
        mapping,
        ("evidence", "retained_frontiers", "closed_families"),
    )
    if not isinstance(closed, list):
        return []
    return sorted(str(item) for item in closed if item)


def _source_model_suppressed_families(mapping: Mapping[str, Any]) -> list[str]:
    suppressed = _nested_value(mapping, ("evidence", "suppressed_families"))
    if not isinstance(suppressed, list):
        return []
    return sorted(str(item) for item in suppressed if item)


def _source_model_suspect_assumption(
    *,
    function: str,
    candidate_scores: Sequence[Mapping[str, Any]],
) -> str:
    families = {
        str(row.get("family") or "")
        for row in candidate_scores
        if row.get("family")
    }
    if function == "mnDiagram_SortNamesByKOs" and (
        "post_ceiling_sort_loop_shape" in families
        or "post_ceiling_sort_swap_materialization" in families
    ):
        return (
            "Sort loop pointer progression and selected-slot address/copy "
            "materialization are now the suspect source-model boundary; "
            "local copy-product, source-owner, select-order, and node-set "
            "families have been exhausted without moving IG34/IG44 onto the "
            "target registers."
        )
    if function == "mnDiagram_DrawCellNumber" and (
        "post_ceiling_statement_grouping" in families
        or "post_ceiling_paired_owner_baseline" in families
        or "post_ceiling_call_temp_materialization" in families
    ):
        return (
            "DrawCellNumber's row/column offset expressions and digit-animation "
            "call/fsubs boundary are now the unmapped source spans; "
            "expression-interferer, select-order, copy-survived node-set, and "
            "baseline-escape families have been exhausted without moving the "
            "col_offset, row_offset, and fsubs expression anchors onto the "
            "target FPRs."
        )
    return (
        "Current source shape is below the retained-frontier source model; "
        "all scored post-ceiling source families preserved structure but left "
        "the target anchors on wrong registers."
    )


def _source_model_proof_summary(
    *,
    function: str,
    summary: Mapping[str, Any] | None = None,
    target_anchors: Sequence[Mapping[str, Any]],
    expression_anchors: Sequence[Mapping[str, Any]],
    candidate_scores: Sequence[Mapping[str, Any]],
) -> str:
    raw_summary = summary if isinstance(summary, Mapping) else {}
    targeted = _source_model_best_target_targeted(
        summary=raw_summary,
        target_anchors=target_anchors,
        candidate_scores=candidate_scores,
    )
    matched = _source_model_best_target_matched(
        summary=raw_summary,
        target_anchors=target_anchors,
        candidate_scores=candidate_scores,
    )
    candidate_count = len(candidate_scores)
    if expression_anchors:
        expression_targeted = _source_model_best_expression_targeted(
            summary=raw_summary,
            expression_anchors=expression_anchors,
            candidate_scores=candidate_scores,
        )
        expression_matched = _source_model_best_expression_matched(
            summary=raw_summary,
            expression_anchors=expression_anchors,
            candidate_scores=candidate_scores,
        )
        return (
            f"{function} reached a post-ceiling FPR expression source-model "
            f"ceiling: {candidate_count} post-ceiling source families scored "
            f"{expression_matched}/{expression_targeted} expression anchors "
            f"and {matched}/{targeted} target anchors, so the next useful lever is a broader source "
            "model rather than another retained-frontier retry."
        )
    return (
        f"{function} reached a post-ceiling source-model ceiling: "
        f"{candidate_count} post-ceiling source families scored {matched}/{targeted} "
        "target anchors, so the next useful lever is a broader source model "
        "rather than another retained-frontier retry."
    )


def _source_model_best_target_matched(
    *,
    summary: Mapping[str, Any],
    target_anchors: Sequence[Mapping[str, Any]],
    candidate_scores: Sequence[Mapping[str, Any]],
) -> int:
    values = [_to_int(summary.get("best_target_matched")) or 0]
    values.append(sum(1 for row in target_anchors if row.get("matched") is True))
    for row in candidate_scores:
        values.append(_to_int(row.get("target_matched")) or 0)
        target_score = row.get("target_score")
        if isinstance(target_score, Mapping):
            values.append(_to_int(target_score.get("matched")) or 0)
            values.append(_score_virtual_match_count(target_score))
    return max(values) if values else 0


def _source_model_best_target_targeted(
    *,
    summary: Mapping[str, Any],
    target_anchors: Sequence[Mapping[str, Any]],
    candidate_scores: Sequence[Mapping[str, Any]],
) -> int:
    values = [_to_int(summary.get("best_target_targeted")) or 0, len(target_anchors)]
    for row in candidate_scores:
        values.append(_to_int(row.get("target_targeted")) or 0)
        target_score = row.get("target_score")
        if isinstance(target_score, Mapping):
            values.append(_to_int(target_score.get("targeted")) or 0)
            virtuals = target_score.get("virtuals")
            if isinstance(virtuals, Mapping):
                values.append(len(virtuals))
    return max(values) if values else 0


def _source_model_best_expression_matched(
    *,
    summary: Mapping[str, Any],
    expression_anchors: Sequence[Mapping[str, Any]],
    candidate_scores: Sequence[Mapping[str, Any]],
) -> int:
    values = [_to_int(summary.get("best_expression_matched")) or 0]
    values.append(sum(1 for row in expression_anchors if row.get("matched") is True))
    for row in candidate_scores:
        values.append(_to_int(row.get("expression_matched")) or 0)
        expression_score = row.get("expression_score")
        if isinstance(expression_score, Mapping):
            values.append(_to_int(expression_score.get("matched")) or 0)
            values.append(_score_virtual_match_count(expression_score))
    return max(values) if values else 0


def _source_model_best_expression_targeted(
    *,
    summary: Mapping[str, Any],
    expression_anchors: Sequence[Mapping[str, Any]],
    candidate_scores: Sequence[Mapping[str, Any]],
) -> int:
    values = [
        _to_int(summary.get("best_expression_targeted")) or 0,
        len(expression_anchors),
    ]
    for row in candidate_scores:
        values.append(_to_int(row.get("expression_targeted")) or 0)
        expression_score = row.get("expression_score")
        if isinstance(expression_score, Mapping):
            values.append(_to_int(expression_score.get("targeted")) or 0)
            virtuals = expression_score.get("virtuals")
            if isinstance(virtuals, Mapping):
                values.append(len(virtuals))
    return max(values) if values else 0


def _score_virtual_match_count(score: Mapping[str, Any]) -> int:
    virtuals = score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return 0
    matched = 0
    for row in virtuals.values():
        if isinstance(row, Mapping) and row.get("matched") is True:
            matched += 1
        elif row is True:
            matched += 1
    return matched


def _source_model_register_class(
    *,
    mapping: Mapping[str, Any],
    expression_anchors: Sequence[Mapping[str, Any]],
) -> str | None:
    if expression_anchors:
        return "fpr"
    for row in _source_model_candidate_score_rows(mapping):
        expression_score = row.get("expression_score")
        if isinstance(expression_score, Mapping):
            register_class = expression_score.get("register_class")
            if register_class:
                return str(register_class)
    return None


def _post_ceiling_continuation_frontier(
    mapping: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    function: str,
    artifact: Path,
    summary_path: str,
) -> dict[str, Any]:
    final_force = _normalized_force_phys(
        mapping.get("final_force_phys")
        or context.get("final_force_phys")
        or _nested_mapping(context, ("evidence", "final_force_phys"))
    )
    attempted = {str(key): value for key, value in final_force.items()}
    terminal = (
        mapping.get("status") == "terminal"
        or mapping.get("kind") == _POST_CEILING_CONTINUATION_TERMINAL_KIND
    )
    ranked = [
        row for row in (mapping.get("ranked_candidates") or [])
        if isinstance(row, Mapping)
    ]
    blockers = [
        row for row in (mapping.get("blockers") or [])
        if isinstance(row, Mapping)
    ]
    candidate_ids = [
        str(row.get("candidate_id"))
        for row in (blockers if terminal else ranked)
        if row.get("candidate_id")
    ]
    route_signatures: list[str] = []
    route_signature_details: list[dict[str, Any]] = []
    for row in ranked:
        continuation = (
            row.get("continuation")
            if isinstance(row.get("continuation"), Mapping)
            else None
        )
        if not isinstance(continuation, Mapping):
            continue
        signature = _post_ceiling_route_signature(
            route=str(continuation.get("route") or ""),
            function=function,
            class_id=_to_int(mapping.get("class_id")),
            target_orders=_normalized_target_orders(
                continuation.get("target_orders")
            ),
            final_force=(
                _normalized_force_phys(row.get("candidate_force_phys"))
                or final_force
            ),
            source_file=_non_empty_str(continuation.get("source_retained")),
            pcdump=_non_empty_str(continuation.get("pcdump_path")),
        )
        if signature is None:
            continue
        route_signatures.append(signature)
        route_signature_details.append({
            "candidate_id": row.get("candidate_id"),
            "route": continuation.get("route"),
            "signature": signature,
            "source_retained": continuation.get("source_retained"),
            "pcdump_path": continuation.get("pcdump_path"),
            "target_orders": continuation.get("target_orders"),
            "candidate_force_phys": row.get("candidate_force_phys"),
        })
    signature = _json_key((final_force, sorted(candidate_ids)))
    frontier_id = _frontier_id(
        function,
        _POST_CEILING_CONTINUATION_FAMILY,
        ("force", final_force),
        ("candidates", sorted(candidate_ids)),
    )
    frontier = _base_frontier(
        mapping,
        function=function,
        artifact=artifact,
        summary_path=summary_path,
        family_id=_POST_CEILING_CONTINUATION_FAMILY,
        frontier_id=frontier_id,
        attempted=attempted,
        protected={},
        final_force=final_force,
        terminal=terminal,
    )
    frontier["kind"] = str(
        mapping.get("kind")
        or (
            _POST_CEILING_CONTINUATION_TERMINAL_KIND
            if terminal
            else _POST_CEILING_CONTINUATION_KIND
        )
    )
    frontier["suppression_family"] = _POST_CEILING_CONTINUATION_FAMILY
    frontier["post_ceiling_continuation_signature"] = signature
    frontier["post_ceiling_route_signatures"] = route_signatures
    frontier["post_ceiling_route_signature_details"] = route_signature_details
    frontier["candidate_ids"] = candidate_ids
    frontier["continuation"] = None
    frontier["actionable"] = False
    frontier["metrics"]["ranked_candidate_count"] = len(ranked)
    frontier["metrics"]["blocker_count"] = len(blockers)
    if terminal:
        frontier["terminal_reason"] = (
            _non_empty_str(mapping.get("terminal_reason"))
            or _POST_CEILING_CONTINUATION_TERMINAL_REASON
        )
        frontier["blockers"] = [dict(row) for row in blockers]
        return frontier

    best = ranked[0] if ranked else None
    continuation = (
        best.get("continuation")
        if isinstance(best, Mapping) and isinstance(best.get("continuation"), Mapping)
        else None
    )
    command = (
        _non_empty_str(continuation.get("command"))
        if isinstance(continuation, Mapping)
        else None
    )
    if (
        isinstance(continuation, Mapping)
        and _retained_meta_continuation_has_action(continuation)
    ):
        promoted = {
            "route": continuation.get("route") or "command-hint",
            "candidate_id": best.get("candidate_id") if isinstance(best, Mapping) else None,
        }
        if command:
            promoted["command"] = command
        for key in (
            "source_retained",
            "pcdump_path",
            "source_hunk",
            "source_hunks",
            "source_components",
            "parents",
            "target_score_estimate",
        ):
            if continuation.get(key) is not None:
                promoted[key] = continuation[key]
        frontier["continuation"] = promoted
        frontier["actionable"] = True
    frontier["best_candidate"] = dict(best) if isinstance(best, Mapping) else None
    return frontier


def _post_ceiling_force_from_target_anchors(raw: Any) -> dict[str, int]:
    if not isinstance(raw, list):
        return {}
    out: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        virtual = _to_int(item.get("baseline_virtual"))
        expected = _to_int(item.get("expected"))
        if virtual is not None and expected is not None:
            out[str(virtual)] = expected
    return out


def _base_frontier(
    mapping: Mapping[str, Any],
    *,
    function: str,
    artifact: Path,
    summary_path: str,
    family_id: str,
    frontier_id: str,
    attempted: Mapping[str, int],
    protected: Mapping[str, int],
    final_force: Mapping[str, int],
    terminal: bool,
) -> dict[str, Any]:
    terminal_reason = _terminal_reason(mapping) if terminal else None
    metrics = _metrics(mapping)
    target_score = _candidate_target_score(mapping)
    if target_score:
        if "targeted" not in metrics and target_score.get("targeted") is not None:
            metrics["targeted"] = target_score.get("targeted")
        if "matched" not in metrics and target_score.get("matched") is not None:
            metrics["matched"] = target_score.get("matched")
    return {
        "rank": None,
        "frontier_id": frontier_id,
        "function": function,
        "artifact": str(artifact),
        "summary_path": summary_path,
        "family_id": family_id,
        "kind": str(mapping.get("kind") or ""),
        "status": str(mapping.get("status") or ""),
        "terminal": terminal,
        "terminal_reason": terminal_reason,
        "closed_by": [str(artifact)] if terminal else [],
        "suppressed_by_terminal": False,
        "actionable": False,
        "attempted_targets": dict(attempted),
        "protected_targets": dict(protected),
        "target_hits": {},
        "protected_hits": {},
        "match_percent": _match_percent(mapping),
        "normalized_drift": {key: None for key in _DRIFT_KEYS},
        "metrics": metrics,
        "best_candidate": None,
        "continuation": None,
        "_mtime": _mtime(artifact),
        "_final_force_phys": dict(final_force),
    }


def _merge_frontiers(frontiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for frontier in frontiers:
        frontier_id = frontier["frontier_id"]
        existing = by_id.get(frontier_id)
        if existing is None:
            by_id[frontier_id] = dict(frontier)
            continue
        _merge_frontier(existing, frontier)
    return list(by_id.values())


def _merge_frontier(existing: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    existing_was_unexhausted = not existing.get("terminal")
    incoming_is_terminal = bool(incoming.get("terminal"))
    if incoming_is_terminal:
        existing["terminal"] = True
        existing["actionable"] = False
        existing["continuation"] = None
        existing["terminal_reason"] = (
            incoming.get("terminal_reason") or existing.get("terminal_reason")
        )
        existing["artifact"] = incoming.get("artifact") or existing["artifact"]
        existing["summary_path"] = (
            incoming.get("summary_path") or existing["summary_path"]
        )
    elif existing.get("terminal"):
        existing["actionable"] = False
        existing["continuation"] = None
        existing["suppressed_by_terminal"] = True
    elif not existing.get("terminal"):
        if incoming.get("actionable") and not existing.get("actionable"):
            existing["actionable"] = True
        if incoming.get("continuation") and not existing.get("continuation"):
            existing["continuation"] = incoming.get("continuation")

    if existing_was_unexhausted and incoming_is_terminal:
        existing["suppressed_by_terminal"] = True

    for artifact in incoming.get("closed_by", []) or []:
        if artifact not in existing["closed_by"]:
            existing["closed_by"].append(artifact)
    for key in ("attempted_targets", "protected_targets", "target_hits", "protected_hits"):
        if incoming.get(key):
            existing[key] = dict(incoming[key])
    if incoming.get("best_candidate"):
        existing["best_candidate"] = incoming["best_candidate"]
    if incoming.get("match_percent") is not None:
        existing["match_percent"] = incoming["match_percent"]
    existing_proof_context = dict(existing)
    existing["_mtime"] = max(existing.get("_mtime", 0.0), incoming.get("_mtime", 0.0))
    for key, value in incoming.get("metrics", {}).items():
        if value is not None:
            existing["metrics"][key] = value
    for key, value in incoming.get("normalized_drift", {}).items():
        if value is not None:
            existing["normalized_drift"][key] = value
    for key in (
        "pcode_lever",
        "addi_signature",
        "force_signature",
        "class_id",
        "target_orders",
        "select_order_signature",
        "source_file",
        "pcdump",
        "suppression_family",
        "blocker_targets",
        "final_force_phys",
        "candidate_count",
        "scored_count",
        "best_expression_matched",
        "best_expression_targeted",
        "best_expression_virtual_distance",
        "post_ceiling_continuation_signature",
        "post_ceiling_route_signature",
        "post_ceiling_route_signatures",
        "post_ceiling_route_signature_details",
        "route_terminal_blockers",
        "candidate_ids",
        "blockers",
        "copy_survived_route_signature",
        "copy_survived_route_signatures",
        "copy_survived_route_signature_details",
        "var",
        "target_ig",
        "target_reg",
        "current_reg",
        "source_model_proof",
        "terminal_summary",
        "stack_clean_no_anchor_evidence",
        "post_stack_clean_no_anchor_evidence",
        "protected_loss_negative_evidence",
        "real_score_authority",
        "terminal_blockers",
        "inline_name",
        "expansion_form",
        "shape_body",
        "shape_return",
        "def_file",
        "evidence",
        "exhausted_dimensions",
        "candidate_count",
        "scored_count",
        "best_score_summary",
    ):
        if key == "source_model_proof":
            incoming_proof = incoming.get(key)
            if incoming_proof is not None and _prefer_incoming_source_model_proof(
                existing.get(key),
                incoming_proof,
                existing_terminal=existing_proof_context,
                incoming_terminal=incoming,
            ):
                existing[key] = incoming_proof
            continue
        if key == "stack_clean_no_anchor_evidence":
            if incoming.get(key) is not None and not existing.get(key):
                existing[key] = incoming[key]
            continue
        if key == "post_stack_clean_no_anchor_evidence":
            if incoming.get(key) is not None and not existing.get(key):
                existing[key] = incoming[key]
            continue
        if incoming.get(key) is not None:
            existing[key] = incoming[key]
    if incoming.get("_final_force_phys"):
        existing["_final_force_phys"] = dict(incoming["_final_force_phys"])


def _prefer_incoming_source_model_proof(
    existing: Any,
    incoming: Any,
    *,
    existing_terminal: Mapping[str, Any] | None = None,
    incoming_terminal: Mapping[str, Any] | None = None,
) -> bool:
    if not isinstance(incoming, Mapping):
        return False
    if not isinstance(existing, Mapping):
        return True
    if (
        _retained_terminal_proof_draw_stack_terminal_chain(incoming)
        and _retained_terminal_proof_draw_stack_terminal_chain(existing)
    ):
        incoming_key = _retained_terminal_proof_selection_key(
            incoming_terminal or incoming,
            incoming,
        )
        existing_key = _retained_terminal_proof_selection_key(
            existing_terminal or existing,
            existing,
        )
        if incoming_key != existing_key:
            return incoming_key > existing_key
    return _source_model_proof_evidence_score(incoming) >= (
        _source_model_proof_evidence_score(existing)
    )


def _source_model_proof_evidence_score(raw: Any) -> int:
    if not isinstance(raw, Mapping):
        return 0
    priority = _source_model_proof_priority(raw)
    score = (
        priority[0] * 10_000
        + priority[1] * 1_000
        + priority[2] * 100
        + priority[3]
    )
    if _retained_post_stack_loop_callsite_source_context_completed(raw):
        score += 500
    if raw.get("post_stack_clean_no_anchor_evidence") is not None:
        score += 300
    if (
        raw.get("next_unsupported_source_dimension")
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        or raw.get("next_unsupported_source_family")
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
        or raw.get("next_unsupported_source_model")
        == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
    ):
        score += 200
    if raw.get("stack_clean_no_anchor_evidence") is not None:
        score += 50
    if (
        raw.get("next_unsupported_source_dimension")
        == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    ):
        score += 25
    synthesis = raw.get("source_family_synthesis")
    if isinstance(synthesis, Mapping):
        if synthesis.get("post_stack_clean_no_anchor_evidence") is not None:
            score += 300
        if (
            synthesis.get("next_unsupported_source_dimension")
            == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
            or synthesis.get("next_unsupported_source_family")
            == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
            or synthesis.get("next_unsupported_source_model")
            == _DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
        ):
            score += 200
        if synthesis.get("stack_clean_no_anchor_evidence") is not None:
            score += 50
        if (
            synthesis.get("next_unsupported_source_dimension")
            == _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ):
            score += 25
    candidate_scores = raw.get("candidate_scores")
    if isinstance(candidate_scores, list):
        score += min(len(candidate_scores), 20)
    return score


def _apply_terminal_suppression(frontiers: list[dict[str, Any]]) -> None:
    addi_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("suppression_family") == "addi-copy-product"
    ]
    c2_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("suppression_family") == "c2-sticky-pool"
    ]
    copy_survived_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("suppression_family") == _COPY_SURVIVED_FAMILY
    ]
    select_order_case_c_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("suppression_family")
        == "select-order-case-c-source-exhaustion"
    ]
    post_ceiling_baseline_escape_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("suppression_family")
        == _POST_CEILING_BASELINE_ESCAPE_FAMILY
    ]
    post_ceiling_continuation_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("suppression_family")
        == _POST_CEILING_CONTINUATION_FAMILY
    ]
    protected_loss_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal") and _frontier_concrete_protected_loss_terminal(frontier)
    ]
    post_ceiling_route_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("post_ceiling_route_signature")
    ]
    copy_survived_node_set_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and frontier.get("copy_survived_route_signature")
    ]
    draw_helper_boundary_terminals = [
        frontier for frontier in frontiers
        if _frontier_closes_draw_helper_boundary_handoff(frontier)
    ]
    draw_protected_expression_reconcile_terminals = [
        frontier for frontier in frontiers
        if _frontier_closes_draw_protected_expression_reconcile(frontier)
    ]
    source_model_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and _frontier_closes_source_model_family(frontier)
    ]
    stack_clean_no_anchor_terminals = [
        frontier for frontier in frontiers
        if frontier.get("terminal")
        and _frontier_closes_stack_clean_no_anchor_recovery(frontier)
    ]
    _apply_sort_window_order_common_subexpr_suppression(frontiers)
    for terminal in addi_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if frontier.get("suppression_family") != "addi-copy-product":
                continue
            if frontier.get("addi_signature") != terminal.get("addi_signature"):
                continue
            _close_frontier(frontier, terminal)

    for terminal in c2_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if not _is_c2_suppressible(frontier):
                continue
            if not _force_matches(frontier, terminal):
                continue
            _close_frontier(frontier, terminal)

    for terminal in copy_survived_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if not _is_copy_survived_suppressible(frontier):
                continue
            if not _copy_survived_targets_intersect(frontier, terminal):
                continue
            _close_frontier(frontier, terminal)

    for terminal in select_order_case_c_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if not _is_select_order_case_c_suppressible(frontier):
                continue
            if not _select_order_case_c_matches(frontier, terminal):
                continue
            _close_frontier(frontier, terminal)

    for terminal in post_ceiling_baseline_escape_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if frontier.get("terminal"):
                continue
            if (
                frontier.get("suppression_family")
                != _POST_CEILING_BASELINE_ESCAPE_FAMILY
            ):
                continue
            _close_frontier(frontier, terminal)

    for terminal in post_ceiling_continuation_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if frontier.get("terminal"):
                continue
            if (
                frontier.get("suppression_family")
                != _POST_CEILING_CONTINUATION_FAMILY
            ):
                continue
            if (
                frontier.get("post_ceiling_continuation_signature")
                != terminal.get("post_ceiling_continuation_signature")
            ):
                continue
            _close_frontier(frontier, terminal)

    for terminal in protected_loss_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("terminal"):
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if not _force_matches(frontier, terminal):
                continue
            if not _frontier_estimated_or_stale_continuation(frontier):
                continue
            _close_frontier(frontier, terminal)

    for terminal in stack_clean_no_anchor_terminals:
        terminal_source: Mapping[str, Any] = terminal
        if not _non_empty_str(terminal.get("terminal_reason")):
            terminal_source = {
                **terminal,
                "terminal_reason": (
                    _DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
                ),
            }
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("terminal"):
                continue
            if not _stack_clean_no_anchor_terminal_matches_lane(
                terminal,
                frontier,
            ):
                continue
            _close_frontier(frontier, terminal_source)

    for terminal in draw_helper_boundary_terminals:
        terminal_source: Mapping[str, Any] = terminal
        if not _non_empty_str(terminal.get("terminal_reason")):
            terminal_source = {
                **terminal,
                "terminal_reason": (
                    _DRAW_COUPLED_FPR_HELPER_BOUNDARY_TERMINAL_REASON
                ),
            }
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if frontier.get("terminal"):
                continue
            if (
                frontier.get("suppression_family")
                != _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
            ):
                continue
            _close_frontier(frontier, terminal_source)

    for terminal in draw_protected_expression_reconcile_terminals:
        terminal_source: Mapping[str, Any] = terminal
        if not _non_empty_str(terminal.get("terminal_reason")):
            terminal_source = {
                **terminal,
                "terminal_reason": (
                    _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
                ),
            }
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if frontier.get("terminal"):
                continue
            if not _draw_protected_expression_reconcile_terminal_matches_lane(
                terminal,
                frontier,
            ):
                continue
            _close_frontier(frontier, terminal_source)

    for terminal in source_model_terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if not _source_model_terminal_matches_frontier(terminal, frontier):
                continue
            _close_frontier(frontier, terminal)

    for frontier in frontiers:
        if frontier.get("terminal"):
            continue
        if frontier.get("suppression_family") != _POST_CEILING_CONTINUATION_FAMILY:
            continue
        route_signatures = [
            signature for signature in (
                frontier.get("post_ceiling_route_signatures") or []
            )
            if isinstance(signature, str) and signature
        ]
        if not route_signatures:
            continue
        matching = _post_ceiling_route_terminal_matches(
            frontier,
            route_signatures=route_signatures,
            terminals=post_ceiling_route_terminals,
        )
        if matching is None:
            continue
        _close_post_ceiling_continuation_routes(frontier, matching)

    for frontier in frontiers:
        if frontier.get("terminal"):
            continue
        if frontier.get("suppression_family") != _COPY_SURVIVED_FAMILY:
            continue
        route_signatures = [
            signature for signature in (
                frontier.get("copy_survived_route_signatures") or []
            )
            if isinstance(signature, str) and signature
        ]
        if not route_signatures:
            continue
        matching = _copy_survived_node_set_terminal_matches(
            frontier,
            route_signatures=route_signatures,
            terminals=copy_survived_node_set_terminals,
        )
        if not matching:
            continue
        if len(matching) == len(set(route_signatures)):
            _close_copy_survived_node_set_routes(frontier, matching.values())
        else:
            _advance_copy_survived_node_set_routes(frontier, matching)


def _apply_sort_window_order_common_subexpr_suppression(
    frontiers: list[dict[str, Any]],
) -> None:
    terminals = [
        frontier for frontier in frontiers
        if _is_sort_window_order_end_pointer_terminal(frontier)
    ]
    if not terminals:
        return
    for terminal in terminals:
        for frontier in frontiers:
            if frontier is terminal:
                continue
            if frontier.get("terminal"):
                continue
            if not _is_sort_common_subexpr_residual_frontier(frontier):
                continue
            if frontier.get("function") != terminal.get("function"):
                continue
            if not _sort_window_order_common_subexpr_force_matches(
                frontier,
                terminal,
            ):
                continue
            _close_frontier(frontier, terminal)


def _is_sort_window_order_end_pointer_terminal(
    frontier: Mapping[str, Any],
) -> bool:
    if frontier.get("function") not in {
        "mnDiagram_SortNamesByKOs",
        "mnDiagram_8023FC28",
    }:
        return False
    if frontier.get("family_id") != "retained_gpr_case_c_window_order_continuation":
        return False
    if not frontier.get("terminal"):
        return False
    if frontier.get("terminal_reason") != (
        "ranked-indexed-byte-window-order-probes-exhausted"
    ):
        return False
    attempted = _normalized_int_mapping(frontier.get("attempted_targets"))
    protected = _normalized_int_mapping(frontier.get("protected_targets"))
    if attempted != {"34": 27} or protected != {"44": 25}:
        return False
    metrics = frontier.get("metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
    target_score = _candidate_target_score(frontier)
    matched = (
        _to_int(metrics.get("matched"))
        or _to_int(target_score.get("matched"))
        or _score_virtual_match_count(target_score)
    )
    virtuals = target_score.get("virtuals")
    targeted = (
        _to_int(metrics.get("targeted"))
        or _to_int(target_score.get("targeted"))
        or (len(virtuals) if isinstance(virtuals, Mapping) else 0)
    )
    protected_negative = _to_int(metrics.get("protected_negative_count")) or 0
    return matched >= 1 and targeted >= 2 and protected_negative > 0


def _is_sort_common_subexpr_residual_frontier(frontier: Mapping[str, Any]) -> bool:
    return (
        frontier.get("status") == "residual-hit"
        and frontier.get("family_id") == "retained_gpr_common_subexpr_coalesce_source"
        and isinstance(frontier.get("continuation"), Mapping)
        and frontier["continuation"].get("route")
        == "retained-common-subexpr-residual-handoff"
    )


def _sort_window_order_common_subexpr_force_matches(
    frontier: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    return (
        _normalized_int_mapping(frontier.get("attempted_targets")) == {"34": 27}
        and _normalized_int_mapping(frontier.get("protected_targets")) == {"44": 25}
        and _frontier_force_for_matching(frontier)
        == _frontier_force_for_matching(terminal)
        == {"34": 27, "44": 25}
    )


def _close_frontier(frontier: dict[str, Any], terminal: Mapping[str, Any]) -> None:
    frontier["terminal"] = True
    frontier["actionable"] = False
    frontier["continuation"] = None
    frontier["suppressed_by_terminal"] = True
    frontier["terminal_reason"] = terminal.get("terminal_reason")
    frontier.setdefault("closed_by", [])
    for artifact in terminal.get("closed_by", []) or [terminal.get("artifact")]:
        if artifact and artifact not in frontier["closed_by"]:
            frontier["closed_by"].append(artifact)


def _frontier_closes_draw_helper_boundary_handoff(row: Mapping[str, Any]) -> bool:
    if _retained_draw_helper_boundary_source_completed(row):
        return True
    if _closed_families_include_draw_helper_boundary(row):
        return True
    groups = row.get("terminal_groups")
    if isinstance(groups, Sequence) and not isinstance(groups, (str, bytes)):
        for group in groups:
            if isinstance(group, Mapping) and (
                _closed_families_include_draw_helper_boundary(group)
                or _retained_draw_helper_boundary_source_completed(group)
            ):
                return True
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        if _closed_families_include_draw_helper_boundary(proof):
            return True
        synthesis = proof.get("source_family_synthesis")
        if isinstance(synthesis, Mapping) and (
            _closed_families_include_draw_helper_boundary(synthesis)
            or _retained_draw_helper_boundary_source_completed(synthesis)
        ):
            return True
    return False


def _closed_families_include_draw_helper_boundary(row: Mapping[str, Any]) -> bool:
    closed = row.get("closed_families")
    if isinstance(closed, Sequence) and not isinstance(closed, (str, bytes)):
        return any(
            item == _DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
            for item in closed
        )
    return False


def _frontier_closes_draw_protected_expression_reconcile(
    row: Mapping[str, Any],
) -> bool:
    if not row.get("terminal"):
        return False
    if (
        row.get("suppression_family")
        == _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE
    ):
        return True
    if row.get("family_id") == _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE:
        return True
    if row.get("class_id") == _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_CLASS_ID:
        return True
    if row.get("kind") == _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_CLASS_ID:
        return True
    return False


def _draw_protected_expression_reconcile_terminal_matches_lane(
    terminal: Mapping[str, Any],
    frontier: Mapping[str, Any],
) -> bool:
    family = (
        frontier.get("suppression_family")
        or frontier.get("family_id")
        or _non_empty_str(_nested_value(frontier, ("continuation", "route")))
    )
    if family != _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE:
        return False
    terminal_force = _frontier_force_for_matching(terminal)
    frontier_force = _frontier_force_for_matching(frontier)
    return bool(terminal_force and frontier_force and terminal_force == frontier_force)


def _frontier_closes_source_model_family(row: Mapping[str, Any]) -> bool:
    if row.get("suppression_family") == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY:
        return True
    if row.get("family_id") == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY:
        return True
    if _closed_families_include_source_model_family(row):
        return True
    groups = row.get("terminal_groups")
    if isinstance(groups, Sequence) and not isinstance(groups, (str, bytes)):
        for group in groups:
            if (
                isinstance(group, Mapping)
                and _closed_families_include_source_model_family(group)
            ):
                return True
    proof = row.get("source_model_proof")
    if isinstance(proof, Mapping):
        if _closed_families_include_source_model_family(proof):
            return True
        synthesis = proof.get("source_family_synthesis")
        if (
            isinstance(synthesis, Mapping)
            and _closed_families_include_source_model_family(synthesis)
        ):
            return True
    return False


def _closed_families_include_source_model_family(row: Mapping[str, Any]) -> bool:
    closed = row.get("closed_families")
    if isinstance(closed, Sequence) and not isinstance(closed, (str, bytes)):
        return any(
            item == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
            for item in closed
        )
    return False


def _is_source_model_suppressible(frontier: Mapping[str, Any]) -> bool:
    if frontier.get("terminal"):
        return False
    return (
        frontier.get("suppression_family")
        == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
        or frontier.get("family_id") == _POST_CEILING_SOURCE_MODEL_PROOF_FAMILY
    )


def _source_model_terminal_matches_frontier(
    terminal: Mapping[str, Any],
    frontier: Mapping[str, Any],
) -> bool:
    if terminal.get("function") != frontier.get("function"):
        return False
    if not _is_source_model_suppressible(frontier):
        return False
    if not _frontier_closes_source_model_family(terminal):
        return False
    frontier_force = _frontier_force_for_matching(frontier)
    terminal_force = _frontier_force_for_matching(terminal)
    if not frontier_force or frontier_force != terminal_force:
        return False
    terminal_mtime = _retained_terminal_proof_mtime(terminal)
    frontier_mtime = frontier.get("_mtime")
    if (
        terminal_mtime
        and isinstance(frontier_mtime, (int, float))
        and not isinstance(frontier_mtime, bool)
        and frontier_mtime
        and terminal_mtime < float(frontier_mtime)
    ):
        return False
    frontier_stage = _retained_meta_lane_source_model_stage(frontier)
    terminal_stage = _retained_meta_terminal_source_model_stage(terminal)
    return bool(frontier_stage > 0 and terminal_stage >= frontier_stage)


def _frontier_closes_sort_semantic_recombine(row: Mapping[str, Any]) -> bool:
    if row.get("function") != _SORT_FUNCTION:
        return False
    if not row.get("terminal"):
        return False
    if _frontier_concrete_protected_loss_terminal(row):
        return True
    for source in _sort_semantic_recombine_closure_sources(row):
        if source.get("real_score_authority") == "protected-loss-negative-evidence":
            return True
        if isinstance(source.get("protected_loss_negative_evidence"), Mapping):
            return True
        if _sort_semantic_recombine_score_required_closed(source):
            return True
        semantic = source.get("semantic_recombine")
        if (
            isinstance(semantic, Mapping)
            and _sort_semantic_recombine_score_required_closed(semantic)
        ):
            return True
    return False


def _sort_semantic_recombine_closure_sources(
    row: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    seen: set[int] = set()

    def add(raw: Any) -> None:
        if not isinstance(raw, Mapping):
            return
        identity = id(raw)
        if identity in seen:
            return
        seen.add(identity)
        sources.append(raw)

    add(row)
    proof = row.get("source_model_proof")
    add(proof)
    synthesis = (
        proof.get("source_family_synthesis")
        if isinstance(proof, Mapping)
        else None
    )
    add(synthesis)
    if isinstance(synthesis, Mapping):
        add(synthesis.get("post_ceiling_source_family_discovery"))
    if isinstance(proof, Mapping):
        for semantic in _retained_terminal_semantic_recombine_blocks(proof):
            add(semantic)
    return sources


def _sort_semantic_recombine_score_required_closed(raw: Mapping[str, Any]) -> bool:
    reason = _non_empty_str(raw.get("terminal_reason") or raw.get("reason"))
    if reason == _SORT_SEMANTIC_RECOMBINE_NEEDS_REAL_SCORE_REASON:
        return True
    blockers = _blocker_reason_strings(raw)
    if "no-scored-recombine-evidence" not in blockers:
        return False
    if raw.get("status") in {"blocked", "terminal"}:
        return True
    return raw.get("recommendation") == "score-required"


def _frontier_concrete_protected_loss_terminal(row: Mapping[str, Any]) -> bool:
    if row.get("function") != _SORT_FUNCTION:
        return False
    if not row.get("terminal"):
        return False
    if row.get("real_score_authority") == "protected-loss-negative-evidence":
        return True
    if isinstance(row.get("protected_loss_negative_evidence"), Mapping):
        return True
    proof = row.get("source_model_proof")
    synthesis = (
        proof.get("source_family_synthesis")
        if isinstance(proof, Mapping)
        else None
    )
    if isinstance(synthesis, Mapping):
        if isinstance(synthesis.get("protected_loss_negative_evidence"), Mapping):
            return True
        if _protected_loss_blocker_strings(synthesis):
            return True
    return bool(_protected_loss_blocker_strings(row))


def _frontier_estimated_or_stale_continuation(row: Mapping[str, Any]) -> bool:
    continuation = row.get("continuation")
    if isinstance(continuation, Mapping):
        if continuation.get("target_score_estimate") is not None:
            return True
        route = _non_empty_str(continuation.get("route"))
        if route and not (
            continuation.get("command")
            or continuation.get("source_hunk")
            or _retained_meta_continuation_has_source_edits(continuation)
            or continuation.get("source_retained")
        ):
            return True
    return _contains_estimated_continuation_evidence(row)


def _contains_estimated_continuation_evidence(raw: Any) -> bool:
    if isinstance(raw, Mapping):
        if raw.get("target_score_estimate") is not None:
            return True
        target_score = raw.get("target_score")
        if isinstance(target_score, Mapping) and target_score.get("estimated") is True:
            return True
        structural = raw.get("structural_guard")
        if isinstance(structural, Mapping) and structural.get("estimated") is True:
            return True
        for value in raw.values():
            if _contains_estimated_continuation_evidence(value):
                return True
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return any(_contains_estimated_continuation_evidence(value) for value in raw)
    return False


def _protected_loss_blocker_strings(raw: Any) -> set[str]:
    needles = {
        "real-score-protected-loss",
        "one-hit-recombine-protected-targets-not-jointly-preserved",
        "manual-subhunk-protected-loss-exhausted",
        "lower-drift-candidates-lost-protected-assignments",
    }
    found: set[str] = set()
    if isinstance(raw, Mapping):
        for key in ("reason", "blocker", "terminal_blocker", "terminal_reason"):
            value = _non_empty_str(raw.get(key))
            if value in needles:
                found.add(value)
        for key in ("terminal_blockers", "blockers"):
            value = raw.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for item in value:
                    if isinstance(item, Mapping):
                        found.update(_protected_loss_blocker_strings(item))
                    elif str(item) in needles:
                        found.add(str(item))
            elif isinstance(value, str) and value in needles:
                found.add(value)
        for value in raw.values():
            found.update(_protected_loss_blocker_strings(value))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for value in raw:
            found.update(_protected_loss_blocker_strings(value))
    return found


def _blocker_reason_strings(raw: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(raw, Mapping):
        for key in ("reason", "blocker", "terminal_blocker", "terminal_reason"):
            value = _non_empty_str(raw.get(key))
            if value is not None:
                found.add(value)
        for key in ("terminal_blockers", "blockers"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                found.add(value)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for item in value:
                    if isinstance(item, str) and item:
                        found.add(item)
                    elif isinstance(item, Mapping):
                        found.update(_blocker_reason_strings(item))
        for value in raw.values():
            if isinstance(value, (Mapping, list, tuple)):
                found.update(_blocker_reason_strings(value))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for value in raw:
            found.update(_blocker_reason_strings(value))
    return found


def _post_ceiling_route_terminal_matches(
    frontier: Mapping[str, Any],
    *,
    route_signatures: Sequence[str],
    terminals: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]] | None:
    by_signature: dict[str, list[Mapping[str, Any]]] = {}
    for terminal in terminals:
        if terminal.get("function") != frontier.get("function"):
            continue
        signature = terminal.get("post_ceiling_route_signature")
        if not isinstance(signature, str) or not signature:
            continue
        by_signature.setdefault(signature, []).append(terminal)

    matched: list[Mapping[str, Any]] = []
    for signature in route_signatures:
        signature_matches = by_signature.get(signature, [])
        if not signature_matches:
            return None
        matched.append(signature_matches[0])
    return matched


def _close_post_ceiling_continuation_routes(
    frontier: dict[str, Any],
    terminals: Sequence[Mapping[str, Any]],
) -> None:
    frontier["terminal"] = True
    frontier["actionable"] = False
    frontier["continuation"] = None
    frontier["suppressed_by_terminal"] = True
    frontier["terminal_reason"] = _POST_CEILING_CONTINUATION_ROUTE_TERMINAL_REASON
    blockers: list[dict[str, Any]] = []
    for terminal in terminals:
        for artifact in terminal.get("closed_by", []) or [terminal.get("artifact")]:
            if artifact and artifact not in frontier["closed_by"]:
                frontier["closed_by"].append(artifact)
        blockers.append({
            "artifact": terminal.get("artifact"),
            "kind": terminal.get("kind"),
            "terminal_reason": terminal.get("terminal_reason"),
            "terminal_blocker": (
                terminal.get("metrics", {}).get("terminal_blocker")
                if isinstance(terminal.get("metrics"), Mapping)
                else None
            )
            or terminal.get("terminal_reason"),
            "post_ceiling_route_signature": terminal.get(
                "post_ceiling_route_signature"
            ),
            "target_orders": terminal.get("target_orders"),
            "source_file": terminal.get("source_file"),
            "pcdump": terminal.get("pcdump"),
        })
    frontier["route_terminal_blockers"] = blockers


def _copy_survived_node_set_terminal_matches(
    frontier: Mapping[str, Any],
    *,
    route_signatures: Sequence[str],
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    by_signature: dict[str, list[Mapping[str, Any]]] = {}
    for terminal in terminals:
        if terminal.get("function") != frontier.get("function"):
            continue
        signature = terminal.get("copy_survived_route_signature")
        if not isinstance(signature, str) or not signature:
            continue
        by_signature.setdefault(signature, []).append(terminal)

    matched: dict[str, Mapping[str, Any]] = {}
    for signature in route_signatures:
        signature_matches = by_signature.get(signature, [])
        if signature_matches:
            matched[signature] = signature_matches[0]
    return matched


def _close_copy_survived_node_set_routes(
    frontier: dict[str, Any],
    terminals: Iterable[Mapping[str, Any]],
) -> None:
    frontier["terminal"] = True
    frontier["actionable"] = False
    frontier["continuation"] = None
    frontier["suppressed_by_terminal"] = True
    frontier["terminal_reason"] = _COPY_SURVIVED_NODE_SET_ROUTES_TERMINAL_REASON
    frontier["route_terminal_blockers"] = _copy_survived_node_set_blockers(
        frontier,
        terminals,
    )


def _advance_copy_survived_node_set_routes(
    frontier: dict[str, Any],
    terminals_by_signature: Mapping[str, Mapping[str, Any]],
) -> None:
    frontier["route_terminal_blockers"] = _copy_survived_node_set_blockers(
        frontier,
        terminals_by_signature.values(),
    )
    terminal_signatures = set(terminals_by_signature)
    for detail in frontier.get("copy_survived_route_signature_details") or []:
        if not isinstance(detail, Mapping):
            continue
        signature = detail.get("signature")
        if not isinstance(signature, str) or signature in terminal_signatures:
            continue
        if detail.get("command"):
            frontier["continuation"] = _copy_survived_route_continuation(detail)
            frontier["actionable"] = True
            return
    frontier["continuation"] = None
    frontier["actionable"] = False


def _copy_survived_node_set_blockers(
    frontier: dict[str, Any],
    terminals: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for terminal in terminals:
        for artifact in terminal.get("closed_by", []) or [terminal.get("artifact")]:
            if artifact and artifact not in frontier["closed_by"]:
                frontier["closed_by"].append(artifact)
        blockers.append({
            "artifact": terminal.get("artifact"),
            "kind": terminal.get("kind"),
            "terminal_reason": terminal.get("terminal_reason"),
            "copy_survived_route_signature": terminal.get(
                "copy_survived_route_signature"
            ),
            "var": terminal.get("var"),
            "target_ig": terminal.get("target_ig"),
            "target_reg": terminal.get("target_reg"),
            "current_reg": terminal.get("current_reg"),
            "final_force_phys": terminal.get("final_force_phys"),
        })
    return blockers


def _is_c2_suppressible(frontier: Mapping[str, Any]) -> bool:
    kind = str(frontier.get("kind") or "")
    family = str(frontier.get("family_id") or "")
    return (
        kind == "retained-source-case-c-target-live-range-interference"
        or "target_live_range" in family
        or "alternate_source_owner" in family
    )


def _force_matches(frontier: Mapping[str, Any], terminal: Mapping[str, Any]) -> bool:
    if frontier.get("force_signature") == terminal.get("force_signature"):
        return True
    frontier_force = frontier.get("_final_force_phys") or {}
    terminal_force = terminal.get("_final_force_phys") or {}
    return bool(frontier_force and frontier_force == terminal_force)


def _is_copy_survived_suppressible(frontier: Mapping[str, Any]) -> bool:
    if frontier.get("terminal"):
        return False
    family = str(frontier.get("family_id") or "")
    kind = str(frontier.get("kind") or "")
    return (
        family.startswith("retained_")
        or kind.startswith("retained-")
        or kind.startswith("retained_")
    )


def _copy_survived_targets_intersect(
    frontier: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    copy_from = {
        value for value in (
            _to_int(raw)
            for raw in terminal.get("_copy_survived_from_igs", []) or []
        )
        if value is not None
    }
    if not copy_from:
        return False
    frontier_targets = _frontier_target_igs(frontier)
    return bool(copy_from & frontier_targets)


def _is_select_order_case_c_suppressible(frontier: Mapping[str, Any]) -> bool:
    if frontier.get("terminal"):
        return False
    return (
        frontier.get("suppression_family")
        == "select-order-case-c-source-exhaustion"
        or frontier.get("family_id") == "retained-source-select-order-repair"
    )


def _select_order_case_c_matches(
    frontier: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    if frontier.get("function") != terminal.get("function"):
        return False
    if (
        terminal.get("suppression_family")
        != "select-order-case-c-source-exhaustion"
    ):
        return False
    if not _is_select_order_case_c_suppressible(frontier):
        return False
    frontier_route_signature = frontier.get("post_ceiling_route_signature")
    terminal_route_signature = terminal.get("post_ceiling_route_signature")
    if frontier_route_signature and terminal_route_signature:
        return (
            isinstance(frontier_route_signature, str)
            and isinstance(terminal_route_signature, str)
            and frontier_route_signature == terminal_route_signature
        )
    frontier_class = _to_int(frontier.get("class_id"))
    terminal_class = _to_int(terminal.get("class_id"))
    if (
        frontier_class is not None
        and terminal_class is not None
        and frontier_class != terminal_class
    ):
        return False

    frontier_force = _frontier_force_for_matching(frontier)
    terminal_force = _frontier_force_for_matching(terminal)
    if not frontier_force or frontier_force != terminal_force:
        return False

    frontier_orders = _normalized_target_orders(frontier.get("target_orders"))
    terminal_orders = _normalized_target_orders(terminal.get("target_orders"))
    if frontier_orders and terminal_orders:
        return frontier_orders == terminal_orders

    blocker_targets = set(_normalized_int_sequence(terminal.get("blocker_targets")))
    attempted_targets = {
        parsed for parsed in (
            _to_int(raw) for raw in (frontier.get("attempted_targets") or {})
        )
        if parsed is not None
    }
    return bool(blocker_targets and attempted_targets & blocker_targets)


def _frontier_force_for_matching(frontier: Mapping[str, Any]) -> dict[str, int]:
    force = _normalized_force_phys(frontier.get("_final_force_phys"))
    if not force:
        force = _normalized_force_phys(frontier.get("final_force_phys"))
    if force:
        return force
    attempted = _normalized_int_mapping(frontier.get("attempted_targets"))
    protected = _normalized_int_mapping(frontier.get("protected_targets"))
    return dict(sorted(
        {**protected, **attempted}.items(),
        key=lambda item: _int_sort_key(item[0]),
    ))


def _frontier_target_igs(frontier: Mapping[str, Any]) -> set[int]:
    out: set[int] = set()
    for key in ("attempted_targets", "protected_targets", "_final_force_phys"):
        mapping = frontier.get(key)
        if not isinstance(mapping, Mapping):
            continue
        for raw in mapping:
            parsed = _to_int(raw)
            if parsed is not None:
                out.add(parsed)
    return out


def _rank_frontiers(frontiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(frontiers, key=_rank_key)


def _rank_key(frontier: Mapping[str, Any]) -> tuple[Any, ...]:
    terminal_rank = 1 if frontier.get("terminal") else 0
    category = _category_rank(frontier)
    target_hits = sum(1 for hit in (frontier.get("target_hits") or {}).values() if hit)
    protected_hits = sum(
        1 for hit in (frontier.get("protected_hits") or {}).values() if hit
    )
    drift = frontier.get("normalized_drift") or {}
    normalized_diff = _float_or_inf(drift.get("normalized_diff_lines"))
    distance = min(
        _float_or_inf(drift.get("candidate_final_distance")),
        _float_or_inf(drift.get("target_score_total")),
        _float_or_inf(drift.get("virtual_distance")),
    )
    match_percent = frontier.get("match_percent")
    return (
        terminal_rank,
        category,
        -target_hits,
        -protected_hits,
        normalized_diff,
        distance,
        -float(match_percent) if isinstance(match_percent, (int, float)) else 0.0,
        -float(frontier.get("_mtime") or 0.0),
        str(frontier.get("frontier_id") or ""),
    )


def _category_rank(frontier: Mapping[str, Any]) -> int:
    if frontier.get("terminal"):
        return 7
    status = frontier.get("status")
    if status in {"exact", "scored-exact"}:
        return 1
    continuation = frontier.get("continuation")
    if status == "residual-hit" or (
        isinstance(continuation, Mapping)
        and continuation.get("route") == "source-hunk"
    ):
        return 2
    candidate = frontier.get("best_candidate")
    classification = _classification(candidate)
    if classification in _ACTIONABLE_CLASSIFICATIONS:
        return 3
    if status == "materialized-not-scored":
        return 4
    if isinstance(continuation, Mapping) and continuation.get("command"):
        return 5
    return 6


def _public_frontier(frontier: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        key: value for key, value in frontier.items()
        if not key.startswith("_")
    }
    if out.get("rank") is None:
        out["rank"] = 0
    return out


def _family_id(mapping: Mapping[str, Any], summary_path: str) -> str:
    family = mapping.get("family_id")
    if isinstance(family, str) and family:
        return family
    if summary_path.endswith("retained_case_c_window_order_continuation_summary"):
        return "retained_gpr_case_c_window_order_continuation"
    if summary_path.endswith("retained_case_c_post_source_owner_backtrack_summary"):
        return "retained_gpr_case_c_post_source_owner_backtrack"
    if summary_path.endswith("retained_case_c_target_live_range_repair_summary"):
        return "retained_fpr_case_c_target_live_range_repair"
    if summary_path.endswith("retained_gpr_common_subexpr_coalesce_source_summary"):
        return "retained_gpr_common_subexpr_coalesce_source"
    if summary_path.endswith("retained_case_c_simplify_order_continuation_summary"):
        return "retained_gpr_case_c_simplify_order_continuation"
    if summary_path.endswith("retained_case_c_sensitivity_summary"):
        return "retained_gpr_case_c_sensitivity_search"
    return str(mapping.get("kind") or "retained-frontier")


def _is_retained_summary_kind(kind: Any) -> bool:
    if not isinstance(kind, str):
        return False
    return kind.startswith("retained-") or kind.startswith("retained_")


def _is_terminal_frontier(mapping: Mapping[str, Any]) -> bool:
    status = str(mapping.get("status") or "")
    terminal_blocker = mapping.get("terminal_blocker") or mapping.get("terminal_reason")
    if mapping.get("complete") is True and status.startswith("terminal"):
        return True
    if terminal_blocker in _TERMINAL_REASONS:
        return True
    if terminal_blocker and status in _TERMINAL_STATUSES:
        exact = _to_int(mapping.get("exact_count"))
        return exact in (None, 0)
    return False


def _nested_mapping(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> Mapping[str, Any] | None:
    current = _nested_value(payload, keys)
    return current if isinstance(current, Mapping) else None


def _nested_value(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _terminal_reason(mapping: Mapping[str, Any]) -> str | None:
    for key in ("terminal_blocker", "terminal_reason"):
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    kind = mapping.get("kind")
    if kind == "target-only-backprojection-source-probe-continuation":
        return "target-only-backprojection-source-probe-continuation-terminal"
    if kind == "target-only-c2-sticky-pool-source-attribution":
        return "target-only-c2-sticky-pool-source-attribution-terminal"
    return None


def _is_actionable_frontier(
    mapping: Mapping[str, Any],
    best_candidate: Mapping[str, Any] | None,
) -> bool:
    status = mapping.get("status")
    if status in {"exact", "scored-exact", "residual-hit"}:
        return True
    classification = _classification(best_candidate)
    if classification in _ACTIONABLE_CLASSIFICATIONS:
        return True
    if status == "materialized-not-scored":
        return _candidate_source(best_candidate, mapping) is not None or bool(
            mapping.get("command_hints")
        )
    if status in {"incomplete", "bounded", "source-actionable"}:
        return bool(mapping.get("resume") or mapping.get("command_hints"))
    return False


def _draw_protected_expression_continuation_from_candidate(
    mapping: Mapping[str, Any],
    best_candidate: Mapping[str, Any] | None,
    function: str,
) -> dict[str, Any] | None:
    if function != "mnDiagram_DrawCellNumber" or not isinstance(best_candidate, Mapping):
        return None
    candidate_id = _non_empty_str(best_candidate.get("candidate_id"))
    dimension_id = (
        _non_empty_str(best_candidate.get("dimension_id"))
        or _dimension_from_candidate_id(candidate_id)
    )
    if not candidate_id or not _retained_draw_row_delta_candidate(
        candidate_id,
        dimension_id,
    ):
        return None
    target_score = _mapping_or_none(best_candidate.get("target_score")) or {}
    expression_score = _mapping_or_none(best_candidate.get("expression_score")) or {}
    if _score_matched(best_candidate, target_score, "target") < 1:
        return None
    if _score_matched(best_candidate, expression_score, "expression") != 0:
        return None
    if _score_targeted(best_candidate, expression_score, "expression") in (None, 0):
        return None
    if _row_normalized_diff_lines(best_candidate) != 0:
        return None
    expression_false_positive = (
        _to_int(expression_score.get("false_positive_virtual_id_hit_count")) or 0
    ) > 0
    if not expression_false_positive and not _retained_draw_expression_missing(
        expression_score
    ):
        return None
    source_retained = _candidate_source(best_candidate, mapping)
    pcdump_path = _non_empty_str(
        best_candidate.get("pcdump_path") or mapping.get("pcdump_path")
    )
    raw_source_hunks = best_candidate.get("source_hunks") or mapping.get("source_hunks")
    if not (
        source_retained
        and pcdump_path
        and isinstance(raw_source_hunks, list)
        and raw_source_hunks
    ):
        return None
    source_hunks = _retained_draw_source_hunks_with_protected_subhunks(
        raw_source_hunks
    )
    manual_subhunks = _retained_draw_manual_subhunks(source_hunks)
    continuation: dict[str, Any] = {
        "route": _DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_ROUTE,
        "candidate_id": candidate_id,
        "dimension_id": dimension_id or "draw-row-translation-scale-split",
        "source_retained": source_retained,
        "pcdump_path": pcdump_path,
        "source_hunks": source_hunks,
        "target_score": dict(target_score),
        "expression_score": dict(expression_score),
        "normalized_diff_lines": _row_normalized_diff_lines(best_candidate),
        "command": _retained_draw_protected_expression_command(
            function=function,
            source_retained=source_retained,
        ),
    }
    if manual_subhunks:
        continuation["manual_subhunks"] = manual_subhunks
        continuation["protected_subhunks"] = manual_subhunks
    return continuation


def _common_subexpr_residual_handoff_continuation(
    mapping: Mapping[str, Any],
    best_candidate: Mapping[str, Any] | None,
    function: str,
) -> dict[str, Any] | None:
    if not _is_common_subexpr_residual_hit(mapping):
        return None
    if not isinstance(best_candidate, Mapping):
        return None
    attempted, protected, _final_force, diagnostics = _retained_summary_target_maps(
        mapping,
        best_candidate,
    )
    if not attempted or not protected:
        return None
    source_retained = _candidate_source(best_candidate, mapping)
    pcdump_path = _non_empty_str(
        best_candidate.get("pcdump_path")
        or best_candidate.get("pcdump")
        or mapping.get("pcdump_path")
        or mapping.get("pcdump")
    )
    target_score = _candidate_target_score(best_candidate)
    raw_source_hunks = best_candidate.get("source_hunks") or mapping.get("source_hunks")
    source_hunks = (
        [dict(row) if isinstance(row, Mapping) else row for row in raw_source_hunks]
        if isinstance(raw_source_hunks, list)
        else []
    )
    source_owner_candidates = best_candidate.get("source_owner_candidates")
    if not (
        source_retained
        and pcdump_path
        and target_score
        and (source_hunks or isinstance(source_owner_candidates, list))
    ):
        return None

    continuation: dict[str, Any] = {
        "route": "retained-common-subexpr-residual-handoff",
        "source_retained": source_retained,
        "pcdump_path": pcdump_path,
        "target_score": dict(target_score),
        "source_hunks": source_hunks,
        "preserved_force_phys": dict(diagnostics.get("preserved_force_phys") or protected),
        "protected_force_phys": dict(protected),
        "residual_force_phys": dict(attempted),
        "next_force_phys": dict(attempted),
        "handoff_reason": (
            _non_empty_str(mapping.get("stop_condition"))
            or "common-subexpr-coalesce-source-residual-hit"
        ),
    }
    common_force = diagnostics.get("common_subexpr_force_phys")
    if isinstance(common_force, Mapping):
        continuation["common_subexpr_force_phys"] = dict(common_force)
    for key in (
        "coalesce_pair",
        "common_source_virtual",
        "source_owner_strategy",
        "source_owner_candidates",
    ):
        value = best_candidate.get(key)
        if value is not None:
            continuation[key] = value
    return continuation


def _continuation(
    mapping: Mapping[str, Any],
    best_candidate: Mapping[str, Any] | None,
    function: str,
) -> dict[str, Any] | None:
    draw_protected_expression = _draw_protected_expression_continuation_from_candidate(
        mapping,
        best_candidate,
        function,
    )
    if draw_protected_expression is not None:
        return draw_protected_expression
    common_subexpr_residual = _common_subexpr_residual_handoff_continuation(
        mapping,
        best_candidate,
        function,
    )
    if common_subexpr_residual is not None:
        return common_subexpr_residual
    source_hunk = _candidate_source_hunk(best_candidate)
    source_retained = _candidate_source(best_candidate, mapping)
    if source_hunk is not None:
        return {
            "route": "source-hunk",
            "source_retained": source_retained,
            "source_hunk": source_hunk,
            "source_diff": (
                best_candidate.get("source_diff")
                if isinstance(best_candidate, Mapping)
                else None
            ),
        }
    if source_retained and str(source_retained).endswith(".c"):
        return {
            "route": "score-source",
            "source_retained": source_retained,
            "command": _score_source_command(source_retained, function),
        }
    command_hints = mapping.get("command_hints")
    if isinstance(command_hints, list) and command_hints:
        command = next((item for item in command_hints if isinstance(item, str)), None)
        if command:
            return {"route": "command-hint", "command": command}
    resume = mapping.get("resume")
    if isinstance(resume, Mapping) and resume:
        return {"route": "resume", "resume": dict(resume)}
    return None


def _score_source_command(source_retained: str, function: str) -> str:
    return shlex.join([
        "melee-agent",
        "debug",
        "target",
        "score-source",
        source_retained,
        "--function",
        function,
        "--json",
        "--retain-pcdump",
    ])


def _best_candidate_for_mapping(mapping: Mapping[str, Any]) -> dict[str, Any] | None:
    best_candidate = mapping.get("best_candidate")
    if isinstance(best_candidate, Mapping):
        return _normalized_candidate(best_candidate)
    for key in (
        "ranked_candidates",
        "best_retained_candidates",
        "ranked_retained_candidates",
        "retained_candidates",
        "backtrack_candidates",
        "coalesce_candidates",
        "source_visible_variants",
        "exhausted_strategy_spans",
    ):
        values = mapping.get(key)
        if isinstance(values, list):
            candidates = [
                _normalized_candidate(value)
                for value in values
                if isinstance(value, Mapping)
            ]
            if candidates:
                return sorted(candidates, key=_candidate_rank)[0]
    source_file = mapping.get("source_file") or mapping.get("source_retained")
    if isinstance(source_file, str) and source_file:
        return {
            "probe_id": mapping.get("probe_id"),
            "source_retained": source_file,
            "target_score": _candidate_target_score(mapping),
        }
    return None


def _candidate_rank(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    classification = _classification(candidate)
    class_rank = {
        "exact": 0,
        "residual-hit-protected-lower-drift": 1,
        "lower-drift-frontier": 2,
        "protected-negative": 5,
        "lost-protected": 6,
        "unscoreable": 7,
    }.get(classification, 4)
    target_score = _candidate_target_score(candidate)
    score = target_score.get("total") if isinstance(target_score, Mapping) else None
    direct_score = candidate.get("score")
    return (
        class_rank,
        _float_or_inf(score),
        _float_or_inf(direct_score),
        str(candidate.get("probe_id") or candidate.get("label") or ""),
    )


def _normalized_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(candidate)
    if "source_retained" not in out:
        source_file = out.get("source_file")
        if isinstance(source_file, str) and source_file:
            out["source_retained"] = source_file
    return out


def _classification(candidate: Mapping[str, Any] | None) -> str | None:
    if not isinstance(candidate, Mapping):
        return None
    value = candidate.get("classification")
    if isinstance(value, Mapping):
        value = value.get("classification")
    return value if isinstance(value, str) else None


def _candidate_target_score(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(mapping, Mapping):
        return {}
    target_score = mapping.get("target_score")
    if isinstance(target_score, Mapping):
        return dict(target_score)
    validator = mapping.get("validator_payload")
    if isinstance(validator, Mapping) and isinstance(
        validator.get("target_score"),
        Mapping,
    ):
        return dict(validator["target_score"])
    return {}


def _candidate_source(
    candidate: Mapping[str, Any] | None,
    mapping: Mapping[str, Any],
) -> str | None:
    for source in (candidate, mapping):
        if not isinstance(source, Mapping):
            continue
        for key in ("source_retained", "source_file", "candidate_path", "path"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _candidate_source_hunk(candidate: Mapping[str, Any] | None) -> Any:
    if not isinstance(candidate, Mapping):
        return None
    source_hunk = candidate.get("source_hunk")
    if source_hunk is not None:
        return source_hunk
    source_hunks = candidate.get("source_hunks")
    if isinstance(source_hunks, list) and source_hunks:
        return source_hunks[0]
    return None


def _hit_map(
    candidate: Mapping[str, Any] | None,
    expected: Mapping[str, int],
) -> dict[str, bool]:
    if not expected:
        return {}
    target_score = _candidate_target_score(candidate)
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}
    hits: dict[str, bool] = {}
    for key in expected:
        row = virtuals.get(str(key))
        if isinstance(row, Mapping) and isinstance(row.get("matched"), bool):
            hits[str(key)] = row["matched"]
    return hits


def _normalized_drift(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    target_score = _candidate_target_score(candidate)
    out = {key: None for key in _DRIFT_KEYS}
    if isinstance(candidate, Mapping):
        for key in _DRIFT_KEYS:
            if key in candidate:
                out[key] = candidate[key]
    if target_score:
        out["target_score_total"] = target_score.get("total")
        for key in (
            "virtual_distance",
            "candidate_final_distance",
            "baseline_final_distance",
            "normalized_diff_lines",
        ):
            if target_score.get(key) is not None:
                out[key] = target_score[key]
    return out


def _metrics(mapping: Mapping[str, Any]) -> dict[str, Any]:
    nested_metrics = mapping.get("metrics")
    metrics = dict(nested_metrics) if isinstance(nested_metrics, Mapping) else {}
    metrics.update({key: mapping.get(key) for key in _METRIC_KEYS if key in mapping})
    best = _best_candidate_for_mapping(mapping)
    target_score = _candidate_target_score(best)
    if target_score:
        if target_score.get("targeted") is not None:
            metrics.setdefault("targeted", target_score.get("targeted"))
        if target_score.get("matched") is not None:
            metrics.setdefault("matched", target_score.get("matched"))
    if isinstance(best, Mapping):
        for key in ("target_hits", "protected_preserved", "score"):
            if key in best and key not in metrics:
                metrics[key] = best[key]
    return metrics


def _source_owner_signature(mapping: Mapping[str, Any]) -> tuple[str, ...] | None:
    spans = mapping.get("source_owner_terminal_spans")
    if not isinstance(spans, list):
        return None
    values: list[str] = []
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        for key in (
            "source_expression",
            "current_source_expression",
            "paired_source_expression",
        ):
            value = span.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(sorted(set(values))) or None


def _normalized_force_phys(value: Any) -> dict[str, int]:
    if isinstance(value, Mapping):
        return _normalized_int_mapping(value)
    if not isinstance(value, str):
        return {}
    out: dict[str, int] = {}
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        fields = [field.strip() for field in part.split(":") if field.strip()]
        if len(fields) < 2:
            continue
        ig = _to_int(fields[-2])
        phys = _to_int(fields[-1])
        if ig is None or phys is None:
            continue
        out[str(ig)] = phys
    return dict(sorted(out.items(), key=lambda item: _int_sort_key(item[0])))


def _normalized_target_orders(value: Any) -> tuple[tuple[int, int], ...]:
    pairs: list[tuple[int, int]] = []
    if isinstance(value, str):
        for raw_part in value.split(","):
            part = raw_part.strip().strip("'\"")
            if not part or "<" not in part:
                continue
            left, right = part.split("<", 1)
            before = _register_num(left)
            after = _register_num(right)
            if before is not None and after is not None:
                pairs.append((before, after))
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            if (
                isinstance(item, Sequence)
                and not isinstance(item, (str, bytes, bytearray))
                and len(item) == 2
            ):
                before = _to_int(item[0])
                after = _to_int(item[1])
                if before is not None and after is not None:
                    pairs.append((before, after))
            elif isinstance(item, str):
                pairs.extend(_normalized_target_orders(item))
    return tuple(pairs)


def _normalized_int_sequence(value: Any) -> tuple[int, ...]:
    if isinstance(value, str):
        raw_values: Iterable[Any] = value.split(",")
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_values = value
    else:
        raw_values = ()
    out: list[int] = []
    for raw in raw_values:
        parsed = _register_num(raw)
        if parsed is not None:
            out.append(parsed)
    return tuple(out)


def _command_option(parts: Sequence[str], *names: str) -> str | None:
    if not parts:
        return None
    wanted = set(names)
    for index, part in enumerate(parts):
        if part in wanted and index + 1 < len(parts):
            return parts[index + 1]
        for name in wanted:
            prefix = f"{name}="
            if part.startswith(prefix):
                return part[len(prefix):]
    return None


def _normalized_int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, int] = {}
    for key, raw in value.items():
        parsed = _to_int(raw)
        if parsed is None:
            continue
        out[str(key)] = parsed
    return dict(sorted(out.items(), key=lambda item: _int_sort_key(item[0])))


def _normalized_scalar_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, raw in value.items():
        if isinstance(raw, (str, int, float, bool)) or raw is None:
            out[str(key)] = raw
    return dict(sorted(out.items()))


def _to_int(value: Any) -> int | None:
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


def _register_num(value: Any) -> int | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1].lower() in {"f", "r"}:
            return _to_int(stripped[1:])
        return _to_int(stripped)
    return _to_int(value)


def _non_empty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _int_sort_key(value: str) -> tuple[int, str]:
    parsed = _to_int(value)
    return (parsed if parsed is not None else 10**9, value)


def _frontier_id(function: str, family_id: str, *parts: tuple[str, Any]) -> str:
    joined = "|".join(f"{name}={_json_key(value)}" for name, value in parts)
    return f"{function}|{family_id}|{joined}"


def _force_signature(
    attempted: Mapping[str, int],
    protected: Mapping[str, int],
    final_force: Mapping[str, int],
) -> str:
    return _json_key({
        "attempted": dict(attempted),
        "protected": dict(protected),
        "final": dict(final_force),
    })


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
    return _json_key({
        "route": route,
        "function": function,
        "class_id": class_id,
        "target_orders": [list(order) for order in target_orders],
        "force": dict(final_force),
        "source": _path_signature(source_file),
        "pcdump": _path_signature(pcdump),
    })


def _path_signature(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path)


def _path_suffix_match(left: str, right: str) -> bool:
    normalized_left = left.rstrip("/")
    normalized_right = right.rstrip("/")
    if not normalized_left or not normalized_right:
        return False
    return (
        normalized_left == normalized_right
        or normalized_left.endswith("/" + normalized_right)
        or normalized_right.endswith("/" + normalized_left)
    )


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _match_percent(mapping: Mapping[str, Any]) -> float | None:
    for key in ("current_match_percent", "match_percent", "percent"):
        value = mapping.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _float_or_inf(value: Any) -> float:
    if isinstance(value, bool):
        return math.inf
    if isinstance(value, (int, float)):
        return float(value)
    return math.inf
