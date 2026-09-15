from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

import src.mwcc_debug.post_meta_source_family_synthesis as synthesis
from src.mwcc_debug.allocator_ceiling import (
    classify_allocator_ceiling,
    render_allocator_ceiling_text,
)
from src.mwcc_debug.post_meta_source_family_synthesis import (
    DRAW_FUNCTION,
    DRAW_SOURCE_FUNCTION,
    SORT_FUNCTION,
    SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL,
    SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION,
    SORT_SEMANTIC_RECOMBINE_DIMENSION,
    SORT_SOURCE_FUNCTION,
    build_generated_source_family_payload,
    build_source_family_continuation_payload,
    classify_source_family_scores,
    generate_source_family_candidates,
    materialize_semantic_recombine_source_candidates,
    normalize_meta_ceiling_context,
    resolve_source_function_context,
    score_source_candidates,
    write_source_family_candidates,
)
from src.mwcc_debug.retained_frontier_triage import triage_retained_frontiers
from src.search.cli import search_app

DRAW_COUPLED_UNSUPPORTED_CLASS = "draw-coupled-post-meta-fpr-expression-lifetime"
DRAW_COUPLED_UNSUPPORTED_MODEL = (
    "Draw coupled post-meta FPR expression lifetime/materialization across "
    "col_offset product, row_offset fsubs, and digit-animation fsubs/callarg temp."
)
DRAW_COUPLED_LIFETIME_DIMENSION = "draw-coupled-fpr-expression-lifetime"
DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
)
DRAW_ALTERNATE_DIMENSION = "draw-alternate-fpr-expression-structure"
DRAW_ALTERNATE_TERMINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-alternate-fpr-expression-structure"
)
DRAW_ALTERNATE_TERMINAL_MODEL = (
    "Draw alternate FPR expression-structure synthesis exhausted bounded "
    "coupled col_offset/row_offset/digit-callarg expression graph variants; "
    "no modeled source-actionable Draw family remains."
)
DRAW_ALTERNATE_TERMINAL_BLOCKER = (
    "draw-alternate-fpr-expression-structure-no-floor-improvement"
)
DRAW_POST_ALTERNATE_TERMINAL_BLOCKER = (
    "draw-post-alternate-no-modeled-source-family/current-source-shape-ceiling"
)
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION = (
    "draw-loop-body-callsite-and-object-base-lifetime-source-context"
)
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_TERMINAL_REASON = "draw-loop-body-callsite-and-object-base-lifetime-source-context-exhausted/no-floor-improvement"
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_NO_FLOOR_BLOCKER = "draw-loop-body-callsite-and-object-base-lifetime-source-context/no-target-or-expression-floor-improvement"
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_PATTERN_BLOCKER = "draw-loop-body-callsite-and-object-base-lifetime-source-context/source-patterns-not-found"
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-loop-body-callsite-and-object-base-lifetime-source-context"
DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw loop-body callsite/object-base lifetime source-context synthesis "
    "exhausted bounded preloop object/base lifetime, loop-body callarg/"
    "translate ordering, and lower-hill retained-baseline backtracking source "
    "shapes without improving the retained target/expression floor. No further "
    "modeled source-actionable Draw family remains after this source-context "
    "layer."
)
DRAW_POST_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-source-context-whole-function-fpr-source-model"
)
DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY = "draw-next-unsupported-source-dimension-after-loop-body-callsite-and-object-base-lifetime-source-context"
DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_MODEL = (
    "Draw post-source-context whole-function FPR source model spanning preloop "
    "object/base/data ownership plus loop callsite, translate, animation, and "
    "add-child ownership after loop-body callsite/object-base lifetime "
    "source-context exhaustion."
)
DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-post-source-context-whole-function-fpr-source-model"
DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-source-context whole-function FPR source-model synthesis "
    "exhausted bounded preloop object/base/data ownership plus loop digit "
    "object, animation, translate, and add-child ownership probes without "
    "improving the retained target/real-expression floor. No further modeled "
    "source-actionable Draw family remains after this whole-function layer."
)
DRAW_POST_SOURCE_CONTEXT_NO_FLOOR_BLOCKER = "draw-post-source-context-whole-function-fpr-source-model/no-target-or-real-expression-floor-improvement"
DRAW_POST_SOURCE_CONTEXT_PATTERN_BLOCKER = (
    "draw-post-source-context-whole-function-fpr-source-model/source-patterns-not-found"
)
DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION = (
    "draw-post-all-known-frontiers-source-context-hypothesis"
)
DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_NO_FLOOR_BLOCKER = "draw-post-all-known-frontiers-source-context-hypothesis/no-target-or-real-expression-floor-improvement"
DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-post-all-known-frontiers-source-context-hypothesis"
DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-all-known source-context hypothesis after whole-function FPR "
    "ceiling exhausted bounded recombinations and wider source-context owner "
    "shapes without improving the retained target/real-expression floor."
)
DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION = (
    "draw-post-all-known-loop-product-translate-expression-graph"
)
DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_NO_FLOOR_BLOCKER = "draw-post-all-known-loop-product-translate-expression-graph/no-target-or-real-expression-floor-improvement"
DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-post-all-known-loop-product-translate-expression-graph"
DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_MODEL = (
    "Draw post-all-known loop product/translate expression-graph synthesis "
    "exhausted bounded loop-index translate, col/row product owner, row-delta "
    "product, and common translate-X call-shape variants without improving the "
    "retained target/real-expression floor. No further modeled source-actionable "
    "Draw family remains after this product/translate expression-graph layer."
)
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION = (
    "draw-post-product-translate-stack-clean-no-anchor-recovery"
)
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON = "draw-post-product-translate-stack-clean-no-anchor-recovery-exhausted/no-anchor-recovery"
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER = "draw-post-product-translate-stack-clean-no-anchor-recovery/no-source-actionable-anchor-recovery"
DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-post-product-translate-stack-clean-no-anchor-recovery"
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
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON = "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis-exhausted/no-floor-improvement"
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER = "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis/no-source-actionable-anchor-or-frame-recovery"
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_PATTERN_BLOCKER = "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis/source-span-not-materializable"
DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-fpr-source-shape-hypothesis"
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
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON = "draw-post-stack-clean-no-anchor-loop-callsite-source-context-exhausted/no-floor-improvement"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER = "draw-post-stack-clean-no-anchor-loop-callsite-source-context/no-target-or-expression-floor-improvement"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_PATTERN_BLOCKER = "draw-post-stack-clean-no-anchor-loop-callsite-source-context/source-patterns-not-found"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY = "draw-no-modeled-source-actionable-family-after-post-stack-loop-callsite-source-context"
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor loop-callsite source-context synthesis "
    "exhausted bounded digit object, animation callarg, translate-X/"
    "translate-Y owner, and add-child parent owner probes from the retained "
    "post-stack seed without recovering IG32/IG37/IG46 expression anchors or "
    "eliminating stack-frame drift under the structural guard. No further "
    "modeled source-actionable Draw family remains after this loop-callsite "
    "layer."
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
DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON = "draw-post-stack-loop-callsite-expression-anchor-source-ownership-exhausted/no-owner-progress"
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
    "draw-post-row-offset-owner-expression-lifetime/no-target-or-expression-floor-improvement"
)
DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-expression-lifetime"
)
DRAW_ALTERNATE_SPLIT_BLOCKER = "unsupported-retained-row_offset-product-shape"
DRAW_ALTERNATE_CANDIDATE_IDS = {
    "draw-alternate-fpr-paired-cast-staging-digit-copy",
    "draw-alternate-fpr-row-inline-product-digit-inline",
    "draw-alternate-fpr-row-translation-owner-digit-copy",
    "draw-alternate-fpr-reversed-col-product-digit-fsubs",
    "draw-alternate-fpr-shared-expression-block",
    "draw-alternate-fpr-digit-inline-col-row-reorder",
    "draw-alternate-fpr-paired-cast-staging-digit-fsubs-temp",
    "draw-alternate-fpr-row-delta-before-col-delayed-scale",
}
OLD_SORT_DIMENSIONS = {
    "sort-init-indexed-write",
    "sort-indexed-byte-cache",
    "sort-call-return-copy-local",
    "sort-swap-slot-lvalue",
}
NATURAL_SORT_DIMENSIONS = {
    "sort-natural-init-selection-coupling",
    "sort-natural-selection-state",
    "sort-natural-selected-emission",
    "sort-natural-region-combination",
}
SEMANTIC_SORT_DIMENSIONS = {
    "sort-semantic-loop-ownership",
    "sort-semantic-selection-condition-staging",
    "sort-semantic-selected-name-extraction",
    "sort-semantic-shift-emission-loop",
    "sort-semantic-max-idx-lifetime",
    "sort-semantic-text-total-cache-boundary",
    "sort-semantic-array-pointer-ownership",
    "sort-semantic-region-combination",
}
SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION = (
    "sort-post-cross-tu-broader-natural-c-rewrite"
)
SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite"
)
SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_TERMINAL_REASON = (
    "sort-post-cross-tu-broader-natural-c-rewrite-exhausted/"
    "protected-targets-not-jointly-preserved"
)
SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION = (
    "sort-post-broader-natural-inline-boundary-source-hypothesis"
)
SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis"
)
SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_REASON = (
    "sort-post-broader-natural-inline-boundary-source-hypothesis-exhausted/"
    "protected-targets-not-jointly-preserved"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION = (
    "sort-post-inline-boundary-selection-emission-source-shape"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_PREFIX = (
    "post-meta-sort-post-inline-boundary-selection-emission-"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-post-inline-boundary-"
    "selection-emission-source-shape"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON = (
    "sort-post-inline-boundary-selection-emission-source-shape-exhausted/"
    "protected-targets-not-jointly-preserved"
)
SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_PATTERN_BLOCKER = (
    "sort-post-inline-boundary-selection-emission-source-shape/"
    "source-patterns-not-found"
)


def _sort_source() -> str:
    return """\
typedef unsigned char u8;
typedef unsigned int u32;
typedef char* String;
typedef struct mnDiagram_804A0750_t {
    u8 pad[0x78];
} mnDiagram_804A0750_t;
typedef struct mnDiagram_804A076C_t {
    u8 sorted_names[0x78];
} mnDiagram_804A076C_t;
typedef struct mnDiagram_Assets {
    u8 sorted_fighters[0x78];
    u8 sorted_names[0x78];
} mnDiagram_Assets;
extern mnDiagram_804A0750_t mnDiagram_804A0750;
extern mnDiagram_804A076C_t mnDiagram_804A076C;
extern String GetNameText(u8 idx);
extern u32 mnDiagram_SumNameKOs(u8 idx);
u8 mnDiagram_GetNameByIndex(int idx)
{
    return mnDiagram_804A076C.sorted_names[idx];
}
void mnDiagram_8023FC28(void)
{
    u32 totals[0x78];
    int max_idx;
    u8* dst_iter;
    int i;
    mnDiagram_Assets* assets = (mnDiagram_Assets*) &mnDiagram_804A0750;
    u8* dst = assets->sorted_names;
    u32* tp;
    int n;
    int j;

    dst_iter = dst;
    tp = totals;
    for (n = 0; n < 0x78; n++, dst_iter++, tp++) {
        *dst_iter = (u8) n;
        *tp = mnDiagram_SumNameKOs(n & 0xFF);
    }

    for (i = 0; i < 0x78; i++) {
        max_idx = i;
        for (j = i + 1; j < 0x78; j++) {
            if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != NULL) &&
                ((totals[mnDiagram_804A076C.sorted_names[max_idx]] <
                  totals[mnDiagram_804A076C.sorted_names[j]]) ||
                 ((GetNameText(
                       (0, mnDiagram_804A076C.sorted_names[max_idx])) ==
                   NULL) &&
                  (GetNameText(mnDiagram_804A076C.sorted_names[j]) != NULL))))
            {
                max_idx = j;
            }
        }
        if (max_idx != i) {
            u8* p = &assets->sorted_fighters[max_idx];
            u8 temp = *(p += sizeof(mnDiagram_804A0750_t));
            while (max_idx > i) {
                *p = *(p - 1);
                p--;
                max_idx--;
            }
            dst[i] = temp;
        }
    }
}
"""


def _sort_retained_pointer_seed_source() -> str:
    return """\
typedef unsigned char u8;
typedef unsigned int u32;
typedef char* String;
typedef struct mnDiagram_804A0750_t {
    u8 pad[0x78];
} mnDiagram_804A0750_t;
typedef struct mnDiagram_804A076C_t {
    u8 sorted_names[0x78];
} mnDiagram_804A076C_t;
typedef struct mnDiagram_Assets {
    u8 sorted_fighters[0x78];
    u8 sorted_names[0x78];
} mnDiagram_Assets;
extern mnDiagram_804A0750_t mnDiagram_804A0750;
extern mnDiagram_804A076C_t mnDiagram_804A076C;
extern String GetNameText(u8 idx);
extern u32 mnDiagram_SumNameKOs(u8 idx);
u8* mnDiagram_PostMetaSortUnboundedNamesOwner(void)
{
    return mnDiagram_804A076C.sorted_names;
}
void mnDiagram_SortNamesByKOs(void)
{
    u32 totals[0x78];
    int max_idx;
    u8* dst_iter;
    int i;
    mnDiagram_Assets* assets = (mnDiagram_Assets*) &mnDiagram_804A0750;
    u8* sorted_names = mnDiagram_PostMetaSortUnboundedNamesOwner();
    u8* dst = sorted_names;
    u8* common_source_r39_probe;
    u8 target_repair_live_range_ig39_probe;
    int target_repair_index_ig44_max_idx_probe;
    u32* tp;
    int n;
    int j;

    common_source_r39_probe = dst;
    dst_iter = common_source_r39_probe;
    tp = totals;
    for (n = 0; n < 0x78; n++, dst_iter++, tp++) {
        *dst_iter = (u8) n;
        *tp = mnDiagram_SumNameKOs(n & 0xFF);
    }

    {
        u8* ll_probe_iter_0 = common_source_r39_probe;
        u8* ll_probe_end_0 = dst + 0x78;
        for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {
            max_idx = i;
            for (j = i + 1; j < 0x78; j++) {
                target_repair_index_ig44_max_idx_probe = max_idx;
                target_repair_live_range_ig39_probe = sorted_names[j];
                if ((GetNameText(target_repair_live_range_ig39_probe) != NULL) &&
                    ((totals[sorted_names[target_repair_index_ig44_max_idx_probe]] <
                      totals[sorted_names[j]]) ||
                     ((GetNameText(
                           (0, sorted_names[max_idx])) ==
                       NULL) &&
                      (GetNameText(sorted_names[j]) != NULL))))
                {
                    max_idx = j;
                }
            }
            if (max_idx != i) {
                u8* p = &assets->sorted_fighters[max_idx];
                u8 temp = *(p += sizeof(mnDiagram_804A0750_t));
                while (max_idx > i) {
                    *p = *(p - 1);
                    p--;
                    max_idx--;
                }
                *ll_probe_iter_0 = temp;
            }
        }    }
}
"""


def _sort_source_with_parenthesized_indexes() -> str:
    return (
        _sort_source()
        .replace(
            "mnDiagram_804A076C.sorted_names[max_idx]",
            "mnDiagram_804A076C.sorted_names[(max_idx)]",
        )
        .replace(
            "mnDiagram_804A076C.sorted_names[j]",
            "mnDiagram_804A076C.sorted_names[(j)]",
        )
    )


def _sort_retained_pointer_loop_seed_source() -> str:
    context = _sort_full_selection_swap_context()
    source = _sort_source()
    _function_name, span = synthesis._find_source_function(source, context)
    assert span is not None
    function_text = source[span.sig_start : span.full_end]
    patched_function = synthesis._semantic_sort_patcher(
        selection="visible-first",
        emission="pointer",
    )(function_text)
    assert patched_function is not None
    return source[: span.sig_start] + patched_function + source[span.full_end :]


def _draw_source() -> str:
    return """\
typedef unsigned char u8;
typedef float f32;
typedef struct HSD_JObj HSD_JObj;
typedef struct HSD_GObj {
    void* user_data;
} HSD_GObj;
typedef struct Diagram {
    HSD_JObj* jobjs[13];
} Diagram;
extern f32 HSD_JObjGetTranslationX(HSD_JObj* jobj);
extern f32 HSD_JObjGetTranslationY(HSD_JObj* jobj);
extern HSD_JObj* HSD_JObjLoadJoint(void* joint);
extern void HSD_JObjAddAnimAll(HSD_JObj* jobj, void* a, void* b, void* c);
extern void HSD_JObjReqAnimAll(HSD_JObj* jobj, f32 value);
extern void HSD_JObjAnimAll(HSD_JObj* jobj);
extern void HSD_JObjSetTranslateX(HSD_JObj* jobj, f32 value);
extern void HSD_JObjSetTranslateY(HSD_JObj* jobj, f32 value);
extern void HSD_JObjAddChild(HSD_JObj* parent, HSD_JObj* child);
extern int mn_GetDigitCount(int value);
extern int mn_GetDigitAt(int value, int idx);
extern void* mnDiagram_804A07F4[];
void mnDiagram_80241E78(void* arg0, u8 arg1, u8 arg2, int arg3)
{
    Diagram* data_alias;
    f32 row_offset_adj;
    HSD_JObj* jobj;
    HSD_JObj* jobj2;
    Diagram* data;
    void** joint_data;
    int digit_count;
    int digit;
    int i;
    f32 x_spacing;
    f32 y_spacing;
    f32 base;
    f32 row_offset;
    f32 col_offset;
    u8 col = arg1;
    u8 row = arg2;
    f32 y_offset;

    data = ((HSD_GObj*) arg0)->user_data;
    data_alias = data;

    jobj = data->jobjs[11];
    base = HSD_JObjGetTranslationX(jobj);
    jobj2 = data->jobjs[12];
    x_spacing = HSD_JObjGetTranslationX(jobj2) - base;

    jobj = data->jobjs[7];
    base = HSD_JObjGetTranslationX(jobj);
    jobj2 = data->jobjs[8];
    y_spacing = HSD_JObjGetTranslationX(jobj2) - base;

    jobj = data->jobjs[9];
    base = HSD_JObjGetTranslationY(jobj);
    jobj2 = data->jobjs[10];
    y_offset = HSD_JObjGetTranslationY(jobj2);
    y_offset -= base;

    digit_count = mn_GetDigitCount(arg3);
    col_offset = y_spacing * (f32) col;
    row_offset = y_offset * (f32) row;
    row_offset_adj = row_offset - 0.4f;

    joint_data = mnDiagram_804A07F4;
    for (i = 0; i < digit_count; i++) {
        digit = mn_GetDigitAt(arg3, i);
        jobj = HSD_JObjLoadJoint(joint_data[0]);
        HSD_JObjAddAnimAll(jobj, joint_data[1], joint_data[2], joint_data[3]);
        base = (f32) digit;
        HSD_JObjReqAnimAll(jobj, base);
        HSD_JObjAnimAll(jobj);
        if (col < 7) {
            HSD_JObjSetTranslateX(
                jobj, (x_spacing * (f32) i) + col_offset);
        } else {
            HSD_JObjSetTranslateX(
                jobj, (x_spacing * (f32) i) + col_offset + 0.4f);
        }
        if (row < 10) {
            HSD_JObjSetTranslateY(jobj, row_offset);
        } else {
            HSD_JObjSetTranslateY(jobj, row_offset_adj);
        }
        HSD_JObjAddChild(data_alias->jobjs[11], jobj);
    }
}
"""


def _draw_split_source() -> str:
    return (
        _draw_source()
        .replace(
            "    f32 col_offset;\n    u8 col = arg1;\n",
            "    f32 col_offset;\n    f32 rowf;\n    u8 col = arg1;\n",
        )
        .replace(
            "    y_offset = HSD_JObjGetTranslationY(jobj2);\n    y_offset -= base;\n",
            "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;\n",
        )
        .replace(
            "    col_offset = y_spacing * (f32) col;\n    row_offset = y_offset * (f32) row;\n",
            "    col_offset = (f32) col;\n"
            "    col_offset *= y_spacing;\n"
            "    rowf = (f32) row;\n"
            "    row_offset *= rowf;\n",
        )
    )


def _draw_live_retained_split_source() -> str:
    return (
        _draw_source()
        .replace(
            "extern void* mnDiagram_804A07F4[];\n",
            "typedef struct mnDiagram_ArchiveData {\n"
            "    void* joint;\n"
            "    void* anim_joint;\n"
            "    void* mat_anim;\n"
            "    void* shape_anim;\n"
            "} mnDiagram_ArchiveData;\n"
            "extern mnDiagram_ArchiveData mnDiagram_804A07F4;\n",
        )
        .replace(
            "void mnDiagram_80241E78(void* arg0, u8 arg1, u8 arg2, int arg3)",
            "void mnDiagram_DrawCellNumber(void* gobj, u8 arg1, u8 arg2, int value)",
        )
        .replace(
            "    void** joint_data;\n",
            "    mnDiagram_ArchiveData* joint_data;\n",
        )
        .replace(
            "    f32 col_offset;\n    u8 col = arg1;\n    u8 row = arg2;\n    f32 y_offset;\n",
            "    f32 col_offset;\n    f32 rowf;\n    u8 col = arg1;\n    u8 row = arg2;\n",
        )
        .replace(
            "    data = ((HSD_GObj*) arg0)->user_data;\n",
            "    data = ((HSD_GObj*) gobj)->user_data;\n",
        )
        .replace(
            "    y_offset = HSD_JObjGetTranslationY(jobj2);\n    y_offset -= base;\n",
            "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;\n",
        )
        .replace(
            "    digit_count = mn_GetDigitCount(arg3);\n",
            "    digit_count = mn_GetDigitCount(value);\n",
        )
        .replace(
            "    col_offset = y_spacing * (f32) col;\n    row_offset = y_offset * (f32) row;\n",
            "    col_offset = (f32) col;\n"
            "    col_offset *= y_spacing;\n"
            "    rowf = (f32) row;\n"
            "    row_offset *= rowf;\n",
        )
        .replace(
            "    joint_data = mnDiagram_804A07F4;\n",
            "    joint_data = &mnDiagram_804A07F4;\n",
        )
        .replace(
            "        digit = mn_GetDigitAt(arg3, i);\n",
            "        digit = mn_GetDigitAt(value, i);\n",
        )
        .replace(
            "        jobj = HSD_JObjLoadJoint(joint_data[0]);\n",
            "        jobj = HSD_JObjLoadJoint(joint_data->joint);\n",
        )
        .replace(
            "        HSD_JObjAddAnimAll(jobj, joint_data[1], joint_data[2], joint_data[3]);\n",
            "        HSD_JObjAddAnimAll(jobj, joint_data->anim_joint, joint_data->mat_anim, joint_data->shape_anim);\n",
        )
    )


def _current_ceiling() -> dict:
    return {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "next_unsupported_source_model": "broader Sort source-family synthesis",
        "allocator_facts": [
            {"virtual": 34, "expected": 29, "actual": 24},
            {"virtual": 34, "expected": 27, "actual": 24, "name": "ig34"},
            {"virtual": 44, "expected": 25, "actual": 27, "name": "ig44"},
            {"virtual": 44, "expected": 31, "actual": 27},
        ],
        "source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 810,
                "expression": "addi r34,r39,1",
                "kind": "implicit-temp",
            },
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 823,
                "expression": "add r44,r49,r34",
                "kind": "implicit-temp",
            },
        ],
    }


def _draw_current_ceiling() -> dict:
    return {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        "next_unsupported_source_model": DRAW_COUPLED_UNSUPPORTED_MODEL,
        "allocator_facts": [
            {"virtual": 32, "expected": 28, "actual": 26, "name": "col_offset"},
            {"virtual": 32, "expected": 26, "actual": 26},
            {"virtual": 37, "expected": 26, "actual": 28, "name": "row_offset"},
            {"virtual": 46, "expected": 26, "actual": 1},
        ],
        "source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2564,
                "name": "col_offset",
                "expression": "y_spacing * (f32) col",
                "confidence": "fpr-expression-order",
                "kind": "local",
            },
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2561,
                "name": "row_offset",
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                "confidence": "fpr-expression-order",
                "kind": "local",
            },
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "expression": "fsubs f46,f45,f44",
                "confidence": "pcode-first-def",
                "kind": "fpr-temp",
            },
        ],
    }


def _meta_payload() -> dict:
    return {
        "function": SORT_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"
        ),
        "source_shape_exhausted": True,
        "current_ceiling": _current_ceiling(),
        "retained_frontiers_meta_ceiling": {
            "closed_families": [
                "post-ceiling-source-model-proof",
                "retained-source-select-order-repair",
            ]
        },
    }


def _draw_meta_payload() -> dict:
    return {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"
        ),
        "source_shape_exhausted": True,
        "current_ceiling": _draw_current_ceiling(),
        "retained_frontiers_meta_ceiling": {
            "closed_families": ["post-ceiling-source-model-proof"]
        },
    }


def _frontiers_payload() -> dict:
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": SORT_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [],
                "next_frontier": None,
                "meta_ceiling": {
                    "status": "terminal-current-source-shape-ceiling",
                    "closed_families": ["post-ceiling-source-model-proof"],
                    "terminal_proof": _current_ceiling(),
                },
            }
        ],
        "next_frontier": None,
    }


def _protected_loss_actionable_frontiers_payload(
    *,
    seed_path: str = "build/sort/protected-loss-seed.c",
) -> dict:
    continuation = {
        "route": SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION,
        "candidate_id": "repair-selected-name-owner-dst",
        "parents": [
            "post-meta-sort-semantic-selected-name-after-inner",
            "post-meta-sort-semantic-owner-dst-local-only",
        ],
        "source_retained": seed_path,
        "pcdump_path": "build/sort/protected-loss-seed.pcdump.txt",
        "target_score": _sort_real_target_score(actual34=None, actual44=25),
        "target_score_total": 24,
        "missing_protected_assignments": [{"ig": 34, "phys": 27}],
        "satisfied_protected_assignments": [{"ig": 44, "phys": 25}],
        "protected_assignments_satisfied": False,
        "source_hunks": [
            {"parent": "init", "kind": "decl-lifetime-shape", "base_lines": [20, 21]},
            {"parent": "jtext", "kind": "predicate-shape", "base_lines": [30, 36]},
        ],
        "source_components": [
            _sort_semantic_component("sort-loop-ownership"),
            _sort_semantic_component("sort-selected-name-extraction"),
        ],
    }
    frontier = {
        "frontier_id": "sort-protected-loss-frontier",
        "function": SORT_FUNCTION,
        "kind": "post-meta-source-family-continuation-proof",
        "family_id": "post-ceiling-source-model-proof",
        "status": "actionable",
        "terminal": False,
        "actionable": True,
        "artifact": "/tmp/protected-loss/source-family-continuation.json",
        "final_force_phys": {"34": 27, "44": 25},
        "attempted_targets": {"34": 27, "44": 25},
        "protected_targets": {"34": 27, "44": 25},
        "source_model_proof": {
            "target_anchors": [
                {"virtual": 34, "expected": 27, "actual": None},
                {"virtual": 44, "expected": 25, "actual": 25},
            ],
        },
        "continuation": continuation,
    }
    return {
        "status": "actionable",
        "functions": [
            {
                "function": SORT_FUNCTION,
                "frontiers": [frontier],
                "terminal_frontiers": [],
                "next_frontier": frontier,
                "meta_ceiling": {
                    "status": "actionable",
                    "next_frontier": frontier,
                },
            }
        ],
        "next_frontier": frontier,
    }


def _draw_frontiers_payload() -> dict:
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [],
                "next_frontier": None,
                "meta_ceiling": {
                    "status": "terminal-current-source-shape-ceiling",
                    "closed_families": ["post-ceiling-source-model-proof"],
                    "terminal_proof": _draw_current_ceiling(),
                },
            }
        ],
        "next_frontier": None,
    }


def _context():
    return normalize_meta_ceiling_context(
        [_meta_payload()],
        function=SORT_FUNCTION,
        repo_root=Path.cwd(),
    )


def test_resolve_source_function_context_uses_symbol_present_in_source() -> None:
    context = _context()
    public_source = _sort_source().replace(SORT_SOURCE_FUNCTION, SORT_FUNCTION)

    assert context.source_function == SORT_SOURCE_FUNCTION
    assert (
        resolve_source_function_context(public_source, context).source_function
        == SORT_FUNCTION
    )
    assert (
        resolve_source_function_context(_sort_source(), context).source_function
        == SORT_SOURCE_FUNCTION
    )


def _sort_context_without_broad_natural_evidence():
    context = _context()
    quiet_ceiling = {
        **context.current_ceiling,
        "next_unsupported_source_model": "legacy local source family only",
    }
    return replace(
        context,
        current_ceiling=quiet_ceiling,
        next_unsupported_source_model="legacy local source family only",
    )


def _sort_protected_loss_seed_source() -> str:
    return (
        _sort_source()
        .replace(
            """\
    for (n = 0; n < 0x78; n++, dst_iter++, tp++) {
        *dst_iter = (u8) n;
        *tp = mnDiagram_SumNameKOs(n & 0xFF);
    }
""",
            """\
    for (n = 0; n < 0x78; n++, dst_iter++, tp++) {
        u8 post_meta_name_byte;
        u32 post_meta_total;
        post_meta_name_byte = (u8) n;
        post_meta_total = mnDiagram_SumNameKOs(n & 0xFF);
        *dst_iter = post_meta_name_byte;
        *tp = post_meta_total;
    }
""",
        )
        .replace(
            """\
            if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != NULL) &&
                ((totals[mnDiagram_804A076C.sorted_names[max_idx]] <
                  totals[mnDiagram_804A076C.sorted_names[j]]) ||
                 ((GetNameText(
                       (0, mnDiagram_804A076C.sorted_names[max_idx])) ==
                   NULL) &&
                  (GetNameText(mnDiagram_804A076C.sorted_names[j]) != NULL))))
            {
                max_idx = j;
            }
""",
            """\
            {
                u8 post_ceiling_max_name;
                u8 post_ceiling_j_name;
                char* post_ceiling_max_text;
                char* post_ceiling_j_text;
                char* post_ceiling_j_text_copy;
                post_ceiling_max_name = mnDiagram_804A076C.sorted_names[max_idx];
                post_ceiling_j_name = mnDiagram_804A076C.sorted_names[j];
                post_ceiling_j_text = GetNameText(post_ceiling_j_name);
                post_ceiling_j_text_copy = post_ceiling_j_text;
                post_ceiling_max_text = GetNameText((0, post_ceiling_max_name));
                if ((post_ceiling_j_text_copy != NULL) &&
                    ((totals[post_ceiling_max_name] < totals[post_ceiling_j_name]) ||
                     ((post_ceiling_max_text == NULL) &&
                      (post_ceiling_j_text_copy != NULL))))
                {
                    max_idx = j;
                }
            }
""",
        )
    )


def _sort_semantic_context():
    context = _context()
    ceiling = {
        **context.current_ceiling,
        "next_unsupported_source_model": (
            "Sort natural-region rewrite synthesis exhausted bounded "
            "initialization, selection-state, comparison, and selected-emission "
            "rewrites; the next unsupported source model is an unmodeled semantic "
            "sort algorithm shape outside the bounded natural rewrite generator."
        ),
    }
    return replace(
        context,
        current_ceiling=ceiling,
        next_unsupported_source_model=ceiling["next_unsupported_source_model"],
    )


def _sort_full_selection_swap_context():
    context = _context()
    ceiling = {
        **context.current_ceiling,
        "next_unsupported_source_model": (
            synthesis.SORT_FULL_SELECTION_SWAP_UNSUPPORTED_SOURCE_MODEL
        ),
    }
    return replace(
        context,
        current_ceiling=ceiling,
        next_unsupported_source_model=ceiling["next_unsupported_source_model"],
    )


def _draw_context():
    return normalize_meta_ceiling_context(
        [_draw_meta_payload()],
        function=DRAW_FUNCTION,
        repo_root=Path.cwd(),
    )


def _draw_alternate_context():
    context = _draw_context()
    next_model = (
        "The #1031 Draw source-family continuation exhausted the current retained "
        "baseline lanes. The next unsupported source model is an alternate Draw "
        "FPR expression structure outside current retained baseline assumptions."
    )
    exhausted_dimensions = [
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
        DRAW_COUPLED_LIFETIME_DIMENSION,
        "draw-row-offset-owner-scale",
        "draw-pcode-fsubs-protected-anchor",
    ]
    ceiling = {
        **context.current_ceiling,
        "next_unsupported_source_model": next_model,
        "metrics": {
            "best_target_matched": 1,
            "best_expression_matched": 1,
        },
        "terminal_reason": (
            "post-meta-fpr-expression-hit-continuation-exhausted/protected-anchor-ceiling"
        ),
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "attempted_equivalence_classes": exhausted_dimensions,
            "exhausted_dimensions": [
                {"dimension_id": dimension_id, "status": "scored-terminal"}
                for dimension_id in exhausted_dimensions
            ],
            "retained_scored_probes": [
                {
                    "candidate_id": "draw-coupled-floor",
                    "dimension_id": DRAW_COUPLED_LIFETIME_DIMENSION,
                    "target_matched": 1,
                    "expression_matched": 1,
                    "target_score": {"matched": 1, "targeted": 3},
                    "expression_score": {"matched": 1, "targeted": 3},
                }
            ],
            "next_unsupported_source_model": next_model,
        },
    }
    return replace(
        context,
        current_ceiling=ceiling,
        next_unsupported_source_model=next_model,
    )


def _score(
    candidate: dict,
    *,
    actual34: int = 24,
    actual44: int = 27,
    accepted: bool = True,
    error: str | None = None,
) -> dict:
    payload = {
        "candidate_id": candidate["candidate_id"],
        "source_file": candidate.get("candidate_path") or candidate.get("path"),
        "target_score": {
            "matched": int(actual34 == 27) + int(actual44 == 25),
            "targeted": 2,
            "virtual_distance": int(actual34 != 27) + int(actual44 != 25),
            "virtuals": {
                "34": {
                    "expected": 27,
                    "actual": actual34,
                    "matched": actual34 == 27,
                },
                "44": {
                    "expected": 25,
                    "actual": actual44,
                    "matched": actual44 == 25,
                },
            },
        },
        "structural_guard": {
            "accepted": accepted,
            "normalized_diff_lines": 0,
        },
    }
    if error is not None:
        payload["error"] = error
    return payload


def _sort_semantic_hunk(start: int, end: int | None = None) -> dict:
    end = start + 1 if end is None else end
    return {
        "hunk_id": f"h{start}",
        "base_start": start,
        "base_end": end,
        "candidate_start": start,
        "candidate_end": end,
        "removed": ["old;"],
        "added": ["new;"],
        "kind": "statement",
        "risk": "low",
    }


def _sort_semantic_component(component_id: str) -> dict:
    return {
        "component_id": component_id,
        "role": component_id.removeprefix("sort-").replace("-", " "),
    }


def _sort_one_hit_row(
    candidate_id: str,
    dimension_id: str,
    *,
    hit_virtual: str,
    hunk_start: int | None = None,
    component_id: str = "sort-loop-ownership",
    source_retained: str | None = None,
) -> dict:
    actual34 = 27 if hit_virtual == "34" else 22
    actual44 = 25 if hit_virtual == "44" else 22
    row = {
        "candidate_id": candidate_id,
        "dimension_id": dimension_id,
        "target_matched": 1,
        "target_targeted": 2,
        "target_virtual_distance": 1,
        "target_score": {
            "matched": 1,
            "targeted": 2,
            "virtual_distance": 1,
            "virtuals": {
                "34": {
                    "expected": 27,
                    "actual": actual34,
                    "matched": hit_virtual == "34",
                },
                "44": {
                    "expected": 25,
                    "actual": actual44,
                    "matched": hit_virtual == "44",
                },
            },
        },
        "structural_guard": {
            "accepted": False,
            "normalized_diff_lines": 7,
            "classification_primary": "semantic-one-hit",
        },
        "structural_guard_accepted": False,
        "normalized_diff_lines": 7,
        "source_components": [_sort_semantic_component(component_id)],
        "validation_metadata": {
            "function": SORT_FUNCTION,
            "source_function": SORT_SOURCE_FUNCTION,
            "final_force_phys": {"34": 27, "44": 25},
        },
    }
    if hunk_start is not None:
        row["source_hunks"] = [_sort_semantic_hunk(hunk_start)]
    if source_retained is not None:
        row["source_retained"] = source_retained
    return row


def _sort_one_hit_classified_with_rows(rows: list[dict]) -> dict:
    return {
        "function": SORT_FUNCTION,
        "source_function": SORT_SOURCE_FUNCTION,
        "status": "blocked",
        "reason": "score-rows-not-terminal-safe",
        "score_rows": rows,
        "blockers": [{"reason": "structural-guard-not-accepted"}],
    }


def _sort_post_inline_one_hit_rows(*, include_routes: bool = True) -> list[dict]:
    source_dir = "build/diagnostics/mndiagram_1067_rerun/post_inline_local_write"
    rows = [
        _sort_one_hit_row(
            "post-meta-source-family-sort-init-indexed-write-name-total-locals",
            "sort-init-indexed-write",
            hit_virtual="34",
            hunk_start=10,
            component_id="sort-init-indexed-write-name-total-locals",
            source_retained=(
                f"{source_dir}/"
                "post-meta-source-family-sort-init-indexed-write-name-total-locals.c"
            )
            if include_routes
            else None,
        ),
        _sort_one_hit_row(
            "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
            "sort-call-return-copy-local",
            hit_virtual="44",
            hunk_start=30,
            component_id="sort-call-return-copy-local-max-text-copy",
            source_retained=(
                f"{source_dir}/"
                "post-meta-source-family-sort-call-return-copy-local-max-text-copy.c"
            )
            if include_routes
            else None,
        ),
    ]
    for row, ndiff in zip(rows, (5, 9), strict=True):
        row["normalized_diff_lines"] = ndiff
        row["structural_guard"]["normalized_diff_lines"] = ndiff
        if include_routes:
            row["pcdump_path"] = (
                f"{source_dir}/{row['candidate_id']}.pcdump.txt"
            )
    return rows


def _sort_post_inline_one_hit_classified(
    *,
    include_routes: bool = True,
) -> dict:
    classified = _sort_one_hit_classified_with_rows(
        _sort_post_inline_one_hit_rows(include_routes=include_routes)
    )
    classified["status"] = "terminal"
    classified["source_model_proof"] = {
        "source_family_synthesis": {
            "next_unsupported_source_family": (
                synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
            ),
            "exhausted_dimensions": [
                {
                    "dimension_id": (
                        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
                    ),
                    "status": "scored-terminal",
                    "exhaustion_reason": (
                        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
                    ),
                }
            ],
            "terminal_blockers": [
                synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_BLOCKER
            ],
        }
    }
    return classified


def _sort_post_inline_raw_combine_one_hit(
    *,
    include_route: bool = True,
) -> dict:
    parents = [
        "post-meta-source-family-sort-init-indexed-write-name-total-locals",
        "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
    ]
    target_score = _sort_real_target_score(actual34=22, actual44=25)
    row = {
        "status": "ok",
        "candidate_id": "combine-post-inline-ig34-ig44-lower-drift",
        "parents": parents,
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
            _sort_semantic_hunk(10),
            _sort_semantic_hunk(30),
        ],
        "source_components": [
            _sort_semantic_component(
                "sort-init-indexed-write-name-total-locals"
            ),
            _sort_semantic_component("sort-call-return-copy-local-max-text-copy"),
        ],
        "score_result": {
            "parsed_json": {
                "target_score": target_score,
            }
        },
    }
    if include_route:
        row["path"] = "build/sort/combine-post-inline-ig34-ig44-lower-drift.c"
        row["source_retained"] = row["path"]
        row["pcdump_path"] = (
            "build/sort/combine-post-inline-ig34-ig44-lower-drift.pcdump.txt"
        )
        row["score_result"]["parsed_json"]["source_retained"] = row["path"]
        row["score_result"]["parsed_json"]["pcdump_path"] = row["pcdump_path"]
    return {
        "kind": "debug-search-combine",
        "function": SORT_FUNCTION,
        "combinations": [row],
    }


def _draw_score(
    candidate: dict,
    *,
    actual32: int = 26,
    actual37: int = 28,
    actual46: int = 1,
    expression_actual32: int = 26,
    expression_actual37: int = 28,
    expression_actual46: int = 1,
    accepted: bool = True,
    error: str | None = None,
) -> dict:
    target_matched = int(actual32 == 28) + int(actual37 == 26) + int(actual46 == 26)
    expression_matched = (
        int(expression_actual32 == 28)
        + int(expression_actual37 == 26)
        + int(expression_actual46 == 26)
    )
    payload = {
        "candidate_id": candidate["candidate_id"],
        "source_file": candidate.get("candidate_path") or candidate.get("path"),
        "target_score": {
            "matched": target_matched,
            "targeted": 3,
            "virtual_distance": 3 - target_matched,
            "virtuals": {
                "32": {"expected": 28, "actual": actual32},
                "37": {"expected": 26, "actual": actual37},
                "46": {"expected": 26, "actual": actual46},
            },
        },
        "expression_score": {
            "register_class": "fpr",
            "matched": expression_matched,
            "targeted": 3,
            "virtual_distance": 3 - expression_matched,
            "virtuals": {
                "32": {"expected": 28, "actual": expression_actual32},
                "37": {"expected": 26, "actual": expression_actual37},
                "46": {"expected": 26, "actual": expression_actual46},
            },
        },
        "structural_guard": {
            "accepted": accepted,
            "normalized_diff_lines": 0,
        },
    }
    if error is not None:
        payload["error"] = error
    return payload


def _draw_expression_virtuals(
    *,
    actual32: int | None = 26,
    actual37: int | None = 28,
    actual46: int | None = 1,
    matched46: bool = False,
) -> dict:
    return {
        "32": {
            "baseline_virtual": 32,
            "expected": 28,
            "status": "wrong-register"
            if actual32 is not None
            else "missing-expression",
            "candidate_virtual": 32 if actual32 is not None else None,
            "actual": actual32,
            "matched": actual32 == 28,
            "signature": {
                "kind": "source-expression",
                "source_kind": "local",
                "name": "col_offset",
                "expression": "y_spacing * (f32) col",
            },
            "baseline_source": {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2360,
                "kind": "local",
                "name": "col_offset",
                "expression": "y_spacing * (f32) col",
            },
        },
        "37": {
            "baseline_virtual": 37,
            "expected": 26,
            "status": "wrong-register",
            "candidate_virtual": 37,
            "actual": actual37,
            "matched": actual37 == 26,
            "signature": {
                "kind": "source-expression",
                "source_kind": "local",
                "name": "row_offset",
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
            },
            "baseline_source": {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2357,
                "kind": "local",
                "name": "row_offset",
                "expression": "HSD_JObjGetTranslationY(jobj2) - base",
            },
        },
        "46": {
            "baseline_virtual": 46,
            "expected": 26,
            "status": "ok" if matched46 else "wrong-register",
            "candidate_virtual": 32 if matched46 else 46,
            "actual": actual46,
            "matched": matched46,
            "renumbered": matched46,
            "signature": {
                "kind": "first-def",
                "source_kind": "fpr-temp",
                "opcode": "fsubs",
                "operands": "<dst>,f45,f44",
            },
            "baseline_source": {
                "source_file": "src/melee/mn/mndiagram.c",
                "kind": "fpr-temp",
                "expression": "fsubs f46,f45,f44",
            },
        },
    }


def _draw_floor_summary_classified() -> dict:
    metadata = {
        "function": DRAW_FUNCTION,
        "source_function": "mnDiagram_DrawCellNumber",
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
    }
    return {
        "function": DRAW_FUNCTION,
        "source_function": "mnDiagram_DrawCellNumber",
        "status": "blocked",
        "score_rows": [
            {
                "candidate_id": "draw-retained-expression-floor",
                "dimension_id": "draw-col-cast-product-local",
                "target_matched": 0,
                "target_targeted": 3,
                "target_virtual_distance": 3,
                "target_score": {
                    "matched": 0,
                    "targeted": 3,
                    "virtuals": {
                        "32": {"expected": 28, "actual": 26, "matched": False},
                        "37": {"expected": 26, "actual": 28, "matched": False},
                        "46": {"expected": 26, "actual": 1, "matched": False},
                    },
                },
                "expression_score": {
                    "register_class": "fpr",
                    "matched": 0,
                    "targeted": 3,
                    "virtual_distance": 3,
                    "virtuals": _draw_expression_virtuals(),
                },
                "expression_matched": 0,
                "expression_targeted": 3,
                "expression_virtual_distance": 3,
                "structural_guard": {
                    "accepted": True,
                    "normalized_diff_lines": 0,
                },
                "structural_guard_accepted": True,
                "validation_metadata": metadata,
            }
        ],
        "score_classification": {
            "terminal_summary": {
                "best_expression_matched": 1,
                "best_expression_targeted": 3,
                "best_target_matched": 0,
                "best_target_targeted": 3,
            }
        },
    }


def _draw_plateau_continuation_artifact(
    *,
    expression_matched: int = 1,
    source_retained: str | None = None,
    actual46: int | None = 26,
) -> dict:
    matched46 = actual46 == 26
    row = {
        "candidate_id": f"draw-continuation-expression-{expression_matched}",
        "dimension_id": "draw-pcode-fsubs-protected-anchor",
        "target_matched": 0,
        "target_targeted": 3,
        "target_virtual_distance": 3,
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26, "matched": False},
                "37": {"expected": 26, "actual": 28, "matched": False},
                "46": {"expected": 26, "actual": 1, "matched": False},
            },
        },
        "expression_score": {
            "register_class": "fpr",
            "matched": expression_matched,
            "targeted": 3,
            "virtual_distance": max(3 - expression_matched, 0),
            "virtuals": _draw_expression_virtuals(
                actual46=actual46,
                matched46=matched46,
            ),
        },
        "expression_matched": expression_matched,
        "expression_targeted": 3,
        "expression_virtual_distance": max(3 - expression_matched, 0),
        "structural_guard": {
            "accepted": True,
            "normalized_diff_lines": 0,
        },
        "structural_guard_accepted": True,
        "blockers": ["missing-focus-expression", "protected-expression-regressed"],
    }
    if source_retained is not None:
        row["source_retained"] = source_retained
    return {
        "kind": "expression-scored-fpr-case-a-c2-exhaustion",
        "status": "actionable",
        "best_candidate": {"expression_matched": 1},
        "ranked_candidates": [row],
    }


def _draw_helper_boundary_suggest_inlines_retained_source_artifact(
    *,
    first_expression_matched: int = 0,
) -> dict:
    def expression_score(matched: int) -> dict:
        return {
            "register_class": "fpr",
            "matched": matched,
            "targeted": 3,
            "virtual_distance": max(3 - matched, 0),
            "virtuals": _draw_expression_virtuals(
                actual32=28 if matched >= 1 else 26,
                actual37=26 if matched >= 3 else 28,
                actual46=26 if matched >= 2 else 1,
                matched46=matched >= 2,
            ),
        }

    target_score = {
        "matched": 1,
        "targeted": 3,
        "virtuals": {
            "32": {"expected": 28, "actual": 28, "matched": True},
            "37": {"expected": 26, "actual": 28, "matched": False},
            "46": {"expected": 26, "actual": 1, "matched": False},
        },
    }
    return {
        "function": DRAW_FUNCTION,
        "status": "ok",
        "score_mode": "score-source",
        "score_output_dir": "/tmp/draw-helper-boundary/score_outputs",
        "score_rows": [
            {
                "candidate_id": "block-macro-0001",
                "family": "inline-local-write-helper",
                "transform_family": "local-write-helper",
                "dimension_id": "inline-local-write-helper-block-macro",
                "kind": "block-macro",
                "source_retained": "/tmp/draw-helper-boundary/block-macro-0001.c",
                "source_file": "/tmp/draw-helper-boundary/block-macro-0001.c",
                "pcdump_path": "/tmp/draw-helper-boundary/block-macro-0001.pcdump.txt",
                "source_hunks": [
                    {
                        "hunk_id": "block-macro-0001-h001",
                        "kind": "statement",
                    }
                ],
                "target_matched": 1,
                "target_targeted": 3,
                "target_virtual_distance": 2,
                "target_score": target_score,
                "expression_matched": first_expression_matched,
                "expression_targeted": 3,
                "expression_virtual_distance": max(3 - first_expression_matched, 0),
                "expression_score": expression_score(first_expression_matched),
                "structural_guard": {
                    "accepted": True,
                    "classification_primary": "normalized-structural-match",
                    "normalized_diff_lines": 0,
                    "frame_delta": None,
                },
                "score_command": "python -m src.cli debug target score-source block-macro-0001.c",
            },
            {
                "candidate_id": "scalar-return-helper-0001",
                "family": "inline-local-write-helper",
                "transform_family": "local-write-helper",
                "dimension_id": "inline-local-write-helper-scalar-return-helper",
                "kind": "scalar-return-helper",
                "source_retained": "/tmp/draw-helper-boundary/scalar-return-helper-0001.c",
                "source_file": "/tmp/draw-helper-boundary/scalar-return-helper-0001.c",
                "pcdump_path": (
                    "/tmp/draw-helper-boundary/"
                    "scalar-return-helper-0001.pcdump.txt"
                ),
                "source_hunks": [
                    {
                        "hunk_id": "scalar-return-helper-0001-h001",
                        "kind": "statement",
                    }
                ],
                "target_matched": 1,
                "target_targeted": 3,
                "target_virtual_distance": 2,
                "target_score": target_score,
                "expression_matched": 0,
                "expression_targeted": 3,
                "expression_virtual_distance": 3,
                "expression_score": expression_score(0),
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
                "score_command": "python -m src.cli debug target score-source scalar-return-helper-0001.c",
            },
        ],
    }


def test_meta_ceiling_context_accepts_top_level_current_ceiling() -> None:
    context = _context()

    assert context.function == SORT_FUNCTION
    assert context.source_function == "mnDiagram_8023FC28"
    assert context.force_phys == {"34": 27, "44": 25}
    assert (
        context.next_unsupported_source_model == "broader Sort source-family synthesis"
    )
    assert {span["expression"] for span in context.source_spans} == {
        "addi r34,r39,1",
        "add r44,r49,r34",
    }
    assert {row["virtual"] for row in context.force_phys_conflicts} == {34, 44}


def test_meta_ceiling_context_accepts_frontiers_aggregate() -> None:
    context = normalize_meta_ceiling_context(
        [_frontiers_payload()],
        function=SORT_FUNCTION,
        repo_root=Path.cwd(),
    )

    assert context.force_phys == {"34": 27, "44": 25}
    assert context.closed_families == ["post-ceiling-source-model-proof"]


def test_meta_ceiling_context_accepts_actionable_protected_loss_frontier() -> None:
    context = normalize_meta_ceiling_context(
        [_protected_loss_actionable_frontiers_payload()],
        function=SORT_FUNCTION,
        repo_root=Path.cwd(),
    )

    assert context.force_phys == {"34": 27, "44": 25}
    assert context.continuation_frontiers[0]["continuation"]["route"] == (
        SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
    )
    assert context.current_ceiling["next_frontier"]["continuation"]["route"] == (
        SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
    )


def test_source_model_synthesis_generates_protected_loss_repair_candidates(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "build" / "sort" / "protected-loss-seed.c"
    seed.parent.mkdir(parents=True)
    seed.write_text(_sort_protected_loss_seed_source(), encoding="utf-8")
    context = normalize_meta_ceiling_context(
        [
            _protected_loss_actionable_frontiers_payload(
                seed_path=str(seed),
            )
        ],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )

    protected = [
        row
        for row in candidates
        if row["dimension_id"] == SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
    ]
    assert protected
    assert all("post_ceiling_j_text_copy" in row["source_text"] for row in protected)
    assert protected[0]["validation_metadata"]["required_preserved_assignments"] == [
        {"ig": 44, "phys": 25}
    ]
    assert protected[0]["validation_metadata"]["required_recovered_assignments"] == [
        {"ig": 34, "phys": 27}
    ]
    assert (
        "debug target score-source"
        in protected[0]["validation_metadata"]["score_source_command_hint"]
    )


def test_source_model_synthesis_cli_accepts_actionable_retained_frontiers(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "mndiagram.c"
    source_path.write_text(_sort_source(), encoding="utf-8")
    seed = tmp_path / "build" / "sort" / "protected-loss-seed.c"
    seed.parent.mkdir(parents=True)
    seed.write_text(_sort_protected_loss_seed_source(), encoding="utf-8")
    retained = tmp_path / "retained.json"
    retained.write_text(
        json.dumps(_protected_loss_actionable_frontiers_payload(seed_path=str(seed))),
        encoding="utf-8",
    )
    output = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(retained),
            "--source-file",
            str(source_path),
            "--write-probes",
            str(output),
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert any(
        row["dimension_id"] == SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
        for row in payload["candidates"]
    )
    assert list(output.glob("*.c"))


def test_draw_meta_ceiling_context_accepts_fpr_expression_targets() -> None:
    context = _draw_context()

    assert context.function == DRAW_FUNCTION
    assert context.source_function == "mnDiagram_80241E78"
    assert context.register_class == "fpr"
    assert context.force_phys == {"32": 28, "37": 26, "46": 26}
    assert context.next_unsupported_source_model == DRAW_COUPLED_UNSUPPORTED_MODEL
    assert {span["expression"] for span in context.source_spans} >= {
        "y_spacing * (f32) col",
        "HSD_JObjGetTranslationY(jobj2) - base",
        "fsubs f46,f45,f44",
    }
    assert {row["virtual"] for row in context.force_phys_conflicts} == {32}


def test_draw_context_accepts_frontiers_aggregate() -> None:
    context = normalize_meta_ceiling_context(
        [_draw_frontiers_payload()],
        function=DRAW_FUNCTION,
        repo_root=Path.cwd(),
    )

    assert context.force_phys == {"32": 28, "37": 26, "46": 26}
    assert context.register_class == "fpr"
    assert context.closed_families == ["post-ceiling-source-model-proof"]


def test_draw_context_preserves_embedded_retained_closed_helper_family() -> None:
    payload = _draw_meta_payload()
    payload["retained_frontiers_meta_ceiling"]["closed_families"] = [
        "post-ceiling-source-model-proof",
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
    ]

    context = normalize_meta_ceiling_context(
        [payload],
        function=DRAW_FUNCTION,
        repo_root=Path.cwd(),
    )
    assert DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION in context.closed_families

    continuation = build_source_family_continuation_payload(payload, [])
    assert DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION in continuation["closed_families"]
    assert (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        in (continuation["evidence"]["retained_frontiers"]["closed_families"])
    )
    assert (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
        in (continuation["source_model_proof"]["closed_families"])
    )


def test_sort_synthesis_generates_required_dimensions_and_probe_metadata() -> None:
    context = _context()
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )

    dimensions = {row["dimension_id"] for row in candidates}
    assert OLD_SORT_DIMENSIONS <= dimensions
    assert NATURAL_SORT_DIMENSIONS <= dimensions
    assert len(candidates) > 4
    assert all(row["source_hunks"] for row in candidates)
    assert all(
        row["target_assignments"] == ["IG34->r27", "IG44->r25"] for row in candidates
    )
    generated = build_generated_source_family_payload(candidates, context)
    assert all(
        row["status"] in {"emitted", "skipped"}
        for row in generated["transform_corpus_adapter_outcomes"]
    )


def test_sort_synthesis_generates_natural_rewrite_dimensions_and_components() -> None:
    context = _context()
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )

    by_id = {row["candidate_id"]: row for row in candidates}
    assert {
        "post-meta-sort-natural-rewrite-sort-natural-selection-state-split-guard-total-state",
        "post-meta-sort-natural-rewrite-sort-natural-selected-emission-move-index-local",
    } <= set(by_id)
    natural = [
        row
        for row in candidates
        if str(row["dimension_id"]).startswith("sort-natural-")
    ]
    assert natural
    assert all(row["validation_metadata"]["natural_rewrite"] is True for row in natural)
    assert all(
        row["validation_metadata"]["score_function"] == SORT_SOURCE_FUNCTION
        for row in natural
    )
    assert all(
        f"--function {SORT_SOURCE_FUNCTION}"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in natural
    )
    assert all(
        row["target_assignments"] == ["IG34->r27", "IG44->r25"] for row in natural
    )
    component_ids = {
        component["component_id"]
        for row in natural
        for component in row["source_components"]
    }
    assert {"sort-comparison-operands", "sort-selected-emission"} <= component_ids
    assert all(
        row["validation_metadata"]["source_components"] == row["source_components"]
        for row in natural
    )


def test_sort_natural_selected_emission_can_replace_max_idx_while_shape() -> None:
    candidates = generate_source_family_candidates(
        _sort_source(),
        _context(),
        max_per_dimension=4,
        include_source=True,
    )
    row = next(
        item
        for item in candidates
        if item["candidate_id"].endswith("for-shift-emission")
    )

    assert "while (max_idx > i)" not in row["source_text"]
    assert "for (post_meta_move_idx = max_idx;" in row["source_text"]


def test_sort_natural_rewrites_are_gated_by_broad_model_evidence() -> None:
    quiet_context = _sort_context_without_broad_natural_evidence()
    quiet_candidates = generate_source_family_candidates(
        _sort_source(),
        quiet_context,
        max_per_dimension=4,
        include_source=True,
    )
    assert not {
        row["dimension_id"]
        for row in quiet_candidates
        if str(row["dimension_id"]).startswith("sort-natural-")
    }

    broad_context = replace(
        quiet_context,
        next_unsupported_source_model="broader natural C sort rewrite",
    )
    broad_candidates = generate_source_family_candidates(
        _sort_source(),
        broad_context,
        max_per_dimension=4,
        include_source=True,
    )
    assert NATURAL_SORT_DIMENSIONS <= {row["dimension_id"] for row in broad_candidates}


def test_sort_semantic_algorithm_shapes_are_gated_by_semantic_evidence() -> None:
    broad_context = replace(
        _sort_context_without_broad_natural_evidence(),
        next_unsupported_source_model="broader natural C sort rewrite",
    )
    broad_candidates = generate_source_family_candidates(
        _sort_source(),
        broad_context,
        max_per_dimension=4,
        include_source=True,
    )
    assert not (
        SEMANTIC_SORT_DIMENSIONS & {row["dimension_id"] for row in broad_candidates}
    )

    old_model_with_terminal_evidence = replace(
        _sort_context_without_broad_natural_evidence(),
        current_ceiling={
            "next_unsupported_source_model": "broader Sort source-family synthesis",
            "closed_families": [
                "post-ceiling-source-model-proof",
                *sorted(NATURAL_SORT_DIMENSIONS),
            ],
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": sorted(NATURAL_SORT_DIMENSIONS),
            },
        },
        next_unsupported_source_model="broader Sort source-family synthesis",
    )
    old_model_candidates = generate_source_family_candidates(
        _sort_source(),
        old_model_with_terminal_evidence,
        max_per_dimension=4,
        include_source=True,
    )
    assert not (
        SEMANTIC_SORT_DIMENSIONS & {row["dimension_id"] for row in old_model_candidates}
    )

    semantic_candidates = generate_source_family_candidates(
        _sort_source(),
        _sort_semantic_context(),
        max_per_dimension=4,
        include_source=True,
    )
    assert SEMANTIC_SORT_DIMENSIONS <= {
        row["dimension_id"] for row in semantic_candidates
    }


def test_sort_semantic_algorithm_shapes_emit_source_actionable_metadata() -> None:
    candidates = generate_source_family_candidates(
        _sort_source(),
        _sort_semantic_context(),
        max_per_dimension=2,
        include_source=True,
    )
    semantic = [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]

    assert semantic
    by_id = {row["candidate_id"]: row for row in semantic}
    assert {
        "post-meta-sort-semantic-inner-owned-best",
        "post-meta-sort-semantic-prefix-insertion",
        "post-meta-sort-semantic-staged-visible-j",
        "post-meta-sort-semantic-shift-counted-for",
        "post-meta-sort-semantic-shift-pointer-walk",
        "post-meta-sort-semantic-cache-total-and-text",
        "post-meta-sort-semantic-max-idx-consumed-as-shift-cursor",
        "post-meta-sort-semantic-owner-dst-local-only",
        "post-meta-sort-semantic-staged-visible-j-shift-pointer-walk",
    } <= set(by_id)
    assert len(by_id) == len(semantic)
    assert len(
        {synthesis._normalized_hunk_signature(row["source_hunks"]) for row in semantic}
    ) == len(semantic)
    assert all(row["source_hunks"] for row in semantic)
    assert all(
        row["validation_metadata"]["semantic_algorithm_shape"] is True
        for row in semantic
    )
    assert all(
        row["validation_metadata"]["requires_target_score_validation"] is True
        for row in semantic
    )
    assert all(
        row["validation_metadata"]["score_function"] == SORT_SOURCE_FUNCTION
        for row in semantic
    )
    assert all(
        f"--function {SORT_SOURCE_FUNCTION}"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in semantic
    )
    assert all(
        row["target_assignments"] == ["IG34->r27", "IG44->r25"] for row in semantic
    )
    assert (
        "while (max_idx > i)"
        not in by_id["post-meta-sort-semantic-shift-pointer-walk"]["source_text"]
    )
    assert (
        "post_meta_insert = dst + max_idx;"
        in by_id["post-meta-sort-semantic-shift-pointer-walk"]["source_text"]
    )
    assert (
        "post_meta_selected_name = dst[max_idx];"
        in by_id["post-meta-sort-semantic-owner-dst-local-only"]["source_text"]
    )


def test_sort_semantic_region_matcher_accepts_parenthesized_max_idx() -> None:
    replacement = "    /* semantic replacement */"

    patched = synthesis._replace_sort_algorithm_region(
        _sort_source_with_parenthesized_indexes(),
        replacement,
    )

    assert patched is not None
    assert patched.count(replacement) == 1
    assert "mnDiagram_804A076C.sorted_names[(max_idx)]" not in patched


def test_sort_semantic_algorithm_shapes_tolerate_parenthesized_indexes() -> None:
    candidates = generate_source_family_candidates(
        _sort_source_with_parenthesized_indexes(),
        _sort_semantic_context(),
        max_per_dimension=2,
        include_source=True,
    )
    semantic = [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]

    assert SEMANTIC_SORT_DIMENSIONS <= {row["dimension_id"] for row in semantic}
    assert semantic
    assert all(row["source_hunks"] for row in semantic)
    assert all(
        row["validation_metadata"]["semantic_algorithm_shape"] is True
        for row in semantic
    )
    assert all(
        row["validation_metadata"]["requires_target_score_validation"] is True
        for row in semantic
    )
    assert all(
        row["validation_metadata"]["score_function"] == SORT_SOURCE_FUNCTION
        for row in semantic
    )


def test_sort_semantic_gated_zero_candidates_reports_dimension_blockers() -> None:
    context = _sort_semantic_context()
    source = _sort_source().replace(
        "for (j = i + 1; j < 0x78; j++)",
        "for (j = i + 2; j < 0x78; j++)",
    )
    candidates = generate_source_family_candidates(
        source,
        context,
        max_per_dimension=2,
        include_source=True,
    )

    assert not [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]

    payload = build_generated_source_family_payload(candidates, context)
    semantic_dimensions = [
        row
        for row in payload["dimensions"]
        if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]

    assert {row["dimension_id"] for row in semantic_dimensions} == (
        SEMANTIC_SORT_DIMENSIONS
    )
    assert all(row["candidate_count"] == 0 for row in semantic_dimensions)
    assert all(row["status"] == "blocked" for row in semantic_dimensions)
    assert all(
        row["blockers"][0]["reason"] == "semantic-source-region-pattern-not-matched"
        for row in semantic_dimensions
    )
    assert all(
        "mnDiagram_804A076C.sorted_names[max_idx or (max_idx)] comparison"
        in row["blockers"][0]["required_patterns"]
        for row in semantic_dimensions
    )
    assert {
        row["dimension_id"] for row in payload["generation_blockers"]
    } == SEMANTIC_SORT_DIMENSIONS


def test_draw_synthesis_generates_fpr_dimensions_and_score_hints() -> None:
    context = _draw_context()
    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )

    dimensions = {row["dimension_id"] for row in candidates}
    assert {
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
    } <= dimensions
    assert {
        "draw-expression-lifetime-product-operand-ownership",
        "draw-expression-lifetime-product-sink-ownership",
        "draw-expression-lifetime-row-offset-sink-branch-ownership",
        "draw-expression-lifetime-digit-guarded-statement-motion",
    } <= dimensions
    candidate_ids = {row["candidate_id"] for row in candidates}
    assert {
        "product-col-cast-owner-materialize",
        "product-combined-operand-owners",
        "product-col-offset-sink-owner",
        "row-translate-sink-owner",
        "digit-guard-product-before-count",
    } <= candidate_ids
    assert len(candidates) > 10
    assert all(row["source_hunks"] for row in candidates)
    assert all(
        row["target_assignments"] == ["IG32->r28", "IG37->r26", "IG46->r26"]
        for row in candidates
    )
    assert all(
        row["validation_metadata"]["register_class"] == "fpr" for row in candidates
    )
    assert all(
        "--expression-reg-class fpr"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in candidates
    )
    assert all(
        row["validation_metadata"]["score_function"] == DRAW_SOURCE_FUNCTION
        for row in candidates
    )
    assert all(
        f"--function {DRAW_SOURCE_FUNCTION}"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in candidates
    )
    adapted = [
        row for row in candidates if row.get("adapted_from_expression_interferer")
    ]
    assert adapted
    assert all(row["origin"] == "expression_interferer_repair" for row in adapted)
    assert all(row["source_hunks"] for row in adapted)
    assert all(row["requires_expression_score_validation"] is True for row in adapted)
    assert all(
        row["validation_metadata"]["requires_expression_score_validation"] is True
        for row in adapted
    )
    assert all(
        row["target_assignments"] == ["IG32->r28", "IG37->r26", "IG46->r26"]
        for row in adapted
    )
    assert all(
        "--expression-reg-class fpr"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in adapted
    )
    generated = build_generated_source_family_payload(candidates, context)
    assert generated["family_id"] == (
        "post-ceiling-fpr-expression-source-model-synthesis"
    )


def test_draw_coupled_fpr_lifetime_lane_generates_for_coupled_ceiling() -> None:
    context = _draw_context()
    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )
    coupled = [
        row
        for row in candidates
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    ]

    assert coupled
    assert {row["candidate_id"] for row in coupled} >= {
        "draw-coupled-fpr-col-factor-row-delta-digit-fsubs",
        "draw-coupled-fpr-col-mul-row-delta-digit-copy",
        "draw-coupled-fpr-col-factor-row-factor-digit-fsubs",
    }
    assert all(row["requires_expression_score_validation"] is True for row in coupled)
    assert all(
        row["validation_metadata"]["coupled_fpr_expression_lifetime_lane"] is True
        for row in coupled
    )
    assert all(
        row["validation_metadata"]["score_function"] == DRAW_SOURCE_FUNCTION
        for row in coupled
    )
    assert all(
        "--expression-reg-class fpr"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in coupled
    )
    assert all(
        row["target_assignments"] == ["IG32->r28", "IG37->r26", "IG46->r26"]
        for row in coupled
    )
    assert all(row["source_hunks"] for row in coupled)
    for row in coupled:
        component_ids = {
            component["component_id"] for component in row["source_components"]
        }
        assert {
            "draw-col-offset-product",
            "draw-row-fsubs",
            "draw-digit-callarg-fsubs",
        } <= component_ids


def test_draw_expression_baseline_is_preserved_in_score_hints() -> None:
    context = _draw_context()
    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=4,
        include_source=True,
        validation_options={
            "expression_baseline": "build/diagnostics/live_current.pcdump.txt",
        },
    )
    coupled = [
        row
        for row in candidates
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    ]

    assert coupled
    assert all(
        row["validation_metadata"]["expression_baseline"]
        == "build/diagnostics/live_current.pcdump.txt"
        for row in coupled
    )
    assert all(
        "--expression-baseline build/diagnostics/live_current.pcdump.txt"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in coupled
    )


def test_draw_coupled_fpr_lifetime_lane_generates_for_split_retained_source() -> None:
    context = _draw_context()
    candidates = generate_source_family_candidates(
        _draw_split_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )
    coupled = [
        row
        for row in candidates
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    ]

    assert coupled
    assert {row["candidate_id"] for row in coupled} >= {
        "draw-coupled-fpr-col-factor-row-delta-digit-fsubs",
        "draw-coupled-fpr-col-mul-row-delta-digit-copy",
        "draw-coupled-fpr-col-factor-row-factor-digit-fsubs",
    }
    assert all(row["requires_expression_score_validation"] is True for row in coupled)
    assert all(
        row["validation_metadata"]["coupled_fpr_expression_lifetime_lane"] is True
        for row in coupled
    )
    assert all(row["source_hunks"] for row in coupled)
    for row in coupled:
        component_ids = {
            component["component_id"] for component in row["source_components"]
        }
        assert {
            "draw-col-offset-product",
            "draw-row-fsubs",
            "draw-digit-callarg-fsubs",
        } <= component_ids

    payload = build_generated_source_family_payload(candidates, context)
    assert DRAW_COUPLED_LIFETIME_DIMENSION not in {
        blocker["dimension_id"] for blocker in payload.get("generation_blockers", [])
    }


def test_draw_coupled_fpr_lifetime_lane_requires_coupled_next_model() -> None:
    context = _draw_context()
    ceiling = {
        key: value
        for key, value in context.current_ceiling.items()
        if key != "unsupported_source_expression_class"
    }
    ceiling["next_unsupported_source_model"] = "legacy draw local source family only"
    context = replace(
        context,
        current_ceiling=ceiling,
        next_unsupported_source_model=ceiling["next_unsupported_source_model"],
    )

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )

    assert DRAW_COUPLED_LIFETIME_DIMENSION not in {
        row["dimension_id"] for row in candidates
    }


def test_draw_alternate_fpr_expression_structure_generates_exclusive_stage() -> None:
    context = _draw_alternate_context()

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        include_source=True,
    )

    alternate = [
        row for row in candidates if row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
    ]
    assert len(alternate) == 8
    assert {row["dimension_id"] for row in candidates} == {DRAW_ALTERNATE_DIMENSION}
    assert {row["candidate_id"] for row in alternate} >= {
        "draw-alternate-fpr-paired-cast-staging-digit-copy",
        "draw-alternate-fpr-shared-expression-block",
        "draw-alternate-fpr-row-delta-before-col-delayed-scale",
    }
    hunk_signatures = {
        synthesis._normalized_hunk_signature(row["source_hunks"]) for row in alternate
    }
    assert len(hunk_signatures) == len(alternate)
    generated = build_generated_source_family_payload(candidates, context)
    assert generated["status"] == "generated"
    assert {
        row["dimension_id"] for row in generated["dimensions"] if row["candidate_count"]
    } == {DRAW_ALTERNATE_DIMENSION}
    assert DRAW_COUPLED_LIFETIME_DIMENSION not in {
        row.get("dimension_id") for row in generated.get("generation_blockers", [])
    }
    for row in alternate:
        metadata = row["validation_metadata"]
        assert metadata["post_ceiling_alternate_expression_structure_lane"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["baseline_target_floor"] == 1
        assert metadata["baseline_expression_floor"] == 1
        assert metadata["score_function"] == DRAW_SOURCE_FUNCTION
        assert metadata["final_force_phys"] == {"32": 28, "37": 26, "46": 26}
        assert row["requires_expression_score_validation"] is True
        assert row["source_hunks"]
        component_ids = {
            component["component_id"] for component in row["source_components"]
        }
        assert {
            "draw-col-offset-expression",
            "draw-row-offset-expression",
            "draw-digit-callarg-expression",
        } <= component_ids
        assert (
            len(metadata["modified_expression_sites"]) >= 2
            or metadata["cross_site_ordering"] is True
        )


def test_draw_alternate_fpr_expression_structure_supports_retained_row_offset_split_shape() -> (
    None
):
    context = _draw_alternate_context()

    candidates = generate_source_family_candidates(
        _draw_split_source(),
        context,
        include_source=True,
    )

    alternate = [
        row for row in candidates if row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
    ]
    assert len(alternate) == 8
    assert {row["dimension_id"] for row in candidates} == {DRAW_ALTERNATE_DIMENSION}
    assert {row["candidate_id"] for row in alternate} == DRAW_ALTERNATE_CANDIDATE_IDS
    assert all(row["source_hunks"] for row in alternate)
    assert all(row["source_components"] for row in alternate)
    hunk_signatures = {
        synthesis._normalized_hunk_signature(row["source_hunks"]) for row in alternate
    }
    assert len(hunk_signatures) == len(alternate)

    generated = build_generated_source_family_payload(candidates, context)
    assert generated["status"] == "generated"
    assert DRAW_ALTERNATE_SPLIT_BLOCKER not in {
        blocker.get("reason") for blocker in generated.get("generation_blockers", [])
    }

    by_id = {row["candidate_id"]: row for row in alternate}
    paired_hunks = "\n".join(
        "\n".join(hunk.get("new_lines") or hunk.get("added") or [])
        for hunk in by_id["draw-alternate-fpr-paired-cast-staging-digit-copy"][
            "source_hunks"
        ]
    )
    assert "post_alt_col_f = (f32) col;" in paired_hunks
    assert "row_offset *= post_alt_row_f;" in paired_hunks
    assert "y_offset" not in paired_hunks

    owner_hunks = "\n".join(
        "\n".join(hunk.get("new_lines") or hunk.get("added") or [])
        for hunk in by_id["draw-alternate-fpr-row-translation-owner-digit-copy"][
            "source_hunks"
        ]
    )
    assert "row_offset = post_alt_row_translation - base;" in owner_hunks
    assert "y_offset" not in owner_hunks

    shared_hunks = "\n".join(
        "\n".join(hunk.get("new_lines") or hunk.get("added") or [])
        for hunk in by_id["draw-alternate-fpr-shared-expression-block"]["source_hunks"]
    )
    assert "post_alt_row_product = post_alt_row_delta * post_alt_row_f;" in shared_hunks
    assert "y_offset" not in shared_hunks


def test_draw_alternate_fpr_expression_structure_requires_alternate_exhaustion() -> (
    None
):
    candidates = generate_source_family_candidates(
        _draw_source(),
        _draw_context(),
        include_source=True,
    )

    assert DRAW_ALTERNATE_DIMENSION not in {row["dimension_id"] for row in candidates}


def test_draw_alternate_max_per_dimension_lifts_default_but_respects_explicit_cap() -> (
    None
):
    context = _draw_alternate_context()

    default_candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        include_source=True,
    )
    capped_candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=2,
        include_source=True,
    )

    assert len(default_candidates) == 8
    assert len(capped_candidates) == 2
    assert {row["dimension_id"] for row in capped_candidates} == {
        DRAW_ALTERNATE_DIMENSION
    }


def test_draw_alternate_fpr_expression_structure_unsupported_split_product_terminalizes() -> (
    None
):
    context = _draw_alternate_context()
    source = _draw_split_source().replace(
        "    rowf = (f32) row;\n    row_offset *= rowf;\n",
        "    row_offset = row_offset * (f32) row;\n",
    )

    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
    )
    payload = build_generated_source_family_payload(candidates, context)

    assert [
        row for row in candidates if row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
    ] == []
    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert payload["next_unsupported_source_model"] == DRAW_ALTERNATE_TERMINAL_MODEL
    blockers = payload["generation_blockers"]
    assert any(
        blocker["dimension_id"] == DRAW_ALTERNATE_DIMENSION
        and blocker["reason"] == DRAW_ALTERNATE_SPLIT_BLOCKER
        for blocker in blockers
    )
    assert DRAW_ALTERNATE_DIMENSION in {
        row["dimension_id"] for row in payload["blocked_dimensions"]
    }
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    assert synthesis_payload["next_unsupported_source_family"] == (
        DRAW_ALTERNATE_TERMINAL_FAMILY
    )
    assert DRAW_ALTERNATE_DIMENSION in {
        row["dimension_id"] for row in synthesis_payload["blocked_dimensions"]
    }
    assert any(
        blocker["reason"] == DRAW_ALTERNATE_SPLIT_BLOCKER
        for blocker in synthesis_payload["generation_blockers"]
    )


def test_draw_coupled_fpr_lifetime_candidate_composes_col_row_digit_moves() -> None:
    context = _draw_context()
    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )
    candidate = next(
        row
        for row in candidates
        if row["candidate_id"] == "draw-coupled-fpr-col-factor-row-delta-digit-fsubs"
    )

    assert "post_meta_col_factor" in candidate["source_text"]
    assert "post_meta_row_delta" in candidate["source_text"]
    assert "base = (f32) digit - 0.0f;" in candidate["source_text"]
    marker_hunks = [
        "\n".join(hunk.get("new_lines") or hunk.get("added") or [])
        for hunk in candidate["source_hunks"]
    ]
    assert len(marker_hunks) >= 2 or any(
        all(
            marker in hunk_text
            for marker in (
                "post_meta_col_factor",
                "post_meta_row_delta",
                "base = (f32) digit - 0.0f;",
            )
        )
        for hunk_text in marker_hunks
    )


def test_draw_coupled_fpr_lifetime_split_candidate_composes_col_row_digit_moves() -> (
    None
):
    context = _draw_context()
    candidates = generate_source_family_candidates(
        _draw_split_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )
    candidate = next(
        row
        for row in candidates
        if row["candidate_id"] == "draw-coupled-fpr-col-factor-row-delta-digit-fsubs"
    )

    assert "post_meta_col_factor" in candidate["source_text"]
    assert "post_meta_row_delta" in candidate["source_text"]
    assert "base = (f32) digit - 0.0f;" in candidate["source_text"]
    hunk_texts = [
        "\n".join(hunk.get("new_lines") or hunk.get("added") or [])
        for hunk in candidate["source_hunks"]
    ]
    assert any("post_meta_col_factor" in hunk_text for hunk_text in hunk_texts)
    assert any("post_meta_row_delta" in hunk_text for hunk_text in hunk_texts)
    assert any("base = (f32) digit - 0.0f;" in hunk_text for hunk_text in hunk_texts)


def test_draw_coupled_fpr_lifetime_terminal_proof_records_coupled_lane(
    tmp_path: Path,
) -> None:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-coupled-probes",
    )
    coupled = [
        row
        for row in candidates
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    ]
    assert coupled

    payload = classify_source_family_scores(
        candidates,
        [_draw_score(row) for row in candidates],
        context,
    )

    assert payload["status"] == "terminal"
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    assert (
        DRAW_COUPLED_LIFETIME_DIMENSION
        in synthesis_payload["attempted_equivalence_classes"]
    )
    assert DRAW_COUPLED_LIFETIME_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    retained = [
        row
        for row in synthesis_payload["retained_scored_probes"]
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    ]
    assert retained
    assert all(row["target_score"] for row in retained)
    assert all(row["expression_score"] for row in retained)
    assert all(row["source_hunks"] for row in retained)
    assert all(row["source_components"] for row in retained)
    assert all(row["requires_expression_score_validation"] is True for row in retained)


def test_draw_generation_blockers_survive_scored_terminal_payload(
    tmp_path: Path,
) -> None:
    context = _draw_context()
    source = _draw_split_source().replace(
        "        base = (f32) digit;\n        HSD_JObjReqAnimAll(jobj, base);",
        "        HSD_JObjReqAnimAll(jobj, (f32) digit);",
    )
    candidates = generate_source_family_candidates(
        source,
        context,
        max_per_dimension=1,
        include_source=True,
    )
    generated = build_generated_source_family_payload(candidates, context)
    generated_blocker = next(
        blocker
        for blocker in generated["generation_blockers"]
        if blocker["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    )
    assert (
        generated_blocker["reason"]
        == "draw-coupled-fpr-source-region-pattern-not-matched"
    )

    written = write_source_family_candidates(
        candidates,
        tmp_path / "draw-generation-blocker-probes",
    )
    payload = classify_source_family_scores(
        written,
        [_draw_score(row) for row in written],
        context,
    )

    assert payload["status"] == "terminal"
    for container in (
        payload,
        payload["post_ceiling_source_family_discovery"],
        payload["source_model_proof"],
        payload["source_model_proof"]["source_family_synthesis"],
    ):
        assert generated_blocker in container["generation_blockers"]
    blocked_dimensions = payload["source_model_proof"]["source_family_synthesis"][
        "blocked_dimensions"
    ]
    blocked = next(
        row
        for row in blocked_dimensions
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    )
    assert blocked["status"] == "blocked"
    assert generated_blocker in blocked["blockers"]


def test_draw_expression_lifetime_adapter_uses_source_alias_before_display_name() -> (
    None
):
    context = replace(_draw_context(), source_function=DRAW_FUNCTION)
    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=4,
        include_source=True,
    )

    adapted = [
        row for row in candidates if row.get("adapted_from_expression_interferer")
    ]
    assert adapted
    assert {row["candidate_id"] for row in adapted} >= {
        "product-col-cast-owner-materialize",
        "row-translate-sink-owner",
    }
    payload = build_generated_source_family_payload(candidates, context)
    assert "target function mnDiagram_DrawCellNumber not found" not in json.dumps(
        payload
    )


def test_write_probes_materializes_candidate_files(tmp_path: Path) -> None:
    context = _context()
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )

    written = write_source_family_candidates(candidates, tmp_path / "probes")

    assert written
    for row in written:
        path = Path(row["candidate_path"])
        assert path.is_file()
        assert path.name.endswith(".c")
        assert len(path.name.encode("utf-8")) < 183
        assert "void mnDiagram_8023FC28(void)" in path.read_text()
        assert "source_text" not in row


def test_score_rows_rank_target_progress_above_structural_only(tmp_path: Path) -> None:
    context = _context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "probes",
    )
    scores = [_score(row) for row in candidates]
    scores[1] = _score(candidates[1], actual34=27, actual44=27)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == candidates[1]["candidate_id"]
    assert payload["best_candidate"]["target_matched"] == 1


def test_draw_score_rows_rank_expression_progress(tmp_path: Path) -> None:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-probes",
    )
    scores = [_draw_score(row) for row in candidates]
    scores[1] = _draw_score(candidates[1], expression_actual32=28)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == candidates[1]["candidate_id"]
    assert payload["best_candidate"]["expression_matched"] == 1
    assert payload["best_candidate"]["target_matched"] == 0


def _draw_alternate_written_candidates(tmp_path: Path) -> tuple[object, list[dict]]:
    context = _draw_alternate_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            include_source=True,
        ),
        tmp_path / "draw-alternate-probes",
    )
    alternate = [
        row for row in candidates if row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
    ]
    assert len(alternate) == 8
    return context, alternate


def _draw_floor_score(candidate: dict, *, pcdump_path: str) -> dict:
    score = _draw_score(
        candidate,
        actual32=28,
        expression_actual32=28,
    )
    score["pcdump_path"] = pcdump_path
    return score


def _draw_alternate_terminal_replay_payload(
    tmp_path: Path,
    *,
    retained_count: int | None = None,
) -> tuple[dict, dict, list[dict], list[dict]]:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    retained_candidates = candidates[:retained_count] if retained_count else candidates
    terminal = classify_source_family_scores(
        retained_candidates,
        [
            _draw_floor_score(
                row,
                pcdump_path=f"build/{row['candidate_id']}.pcdump.txt",
            )
            for row in retained_candidates
        ],
        context,
    )
    terminal_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    payload = build_generated_source_family_payload([], terminal_context)
    return terminal, payload, candidates, retained_candidates


def _draw_post_alternate_source_context(
    tmp_path: Path,
    *,
    retained_count: int | None = 6,
):
    _terminal, payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(
            tmp_path,
            retained_count=retained_count,
        )
    )
    return normalize_meta_ceiling_context(
        [payload],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )


def _draw_post_source_context_handoff_payload() -> dict:
    return {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "current_ceiling": {
            "status": "complete",
            "reason": "post-source-context-next-dimension",
            "current_floor": {"target": 1, "expression": 1},
            "post_source_context_next_dimension": {
                "status": "unsupported-source-dimension",
                "next_unsupported_source_dimension": (
                    DRAW_POST_SOURCE_CONTEXT_DIMENSION
                ),
                "next_unsupported_source_family": (
                    DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY
                ),
                "next_unsupported_source_model": (
                    DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_MODEL
                ),
            },
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": [
                    DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
                ],
                "exhausted_dimensions": [
                    {
                        "dimension_id": (DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION),
                        "status": "scored-terminal",
                    }
                ],
            },
            "retained_scored_probes": [
                {
                    "candidate_id": "draw-post-alt-source-context-floor",
                    "dimension_id": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
                    "target_matched": 1,
                    "expression_matched": 1,
                    "target_score": {"matched": 1, "targeted": 3},
                    "expression_score": {"matched": 1, "targeted": 3},
                    "source_retained": "build/draw/source-context.c",
                    "pcdump_path": "build/draw/source-context.pcdump.txt",
                    "source_hunks": [{"variant_id": "source-context"}],
                }
            ],
        },
        "retained_frontiers_meta_ceiling": {
            "closed_families": ["post-ceiling-source-model-proof"],
        },
    }


def _draw_post_source_context_context():
    return normalize_meta_ceiling_context(
        [_draw_post_source_context_handoff_payload()],
        function=DRAW_FUNCTION,
        repo_root=Path.cwd(),
    )


def _draw_post_source_context_terminal_evidence_row() -> dict:
    return {
        "candidate_id": (
            "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
        ),
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "target_matched": 1,
        "target_targeted": 3,
        "expression_matched": 1,
        "expression_targeted": 3,
        "target_score": {"matched": 1, "targeted": 3, "virtual_distance": 2},
        "expression_score": {"matched": 1, "targeted": 3, "virtual_distance": 2},
        "structural_guard": {
            "accepted": False,
            "reason": "inline-boundary-toolchain-artifact",
            "normalized_diff_lines": 11,
            "opcode_similarity": 0.955684,
        },
        "source_hunks": [{"variant_id": "joint-data-owner-with-loop-object"}],
        "source_components": [
            {"component_id": "draw-whole-function-loop-object-ownership"}
        ],
        "pcdump_path": "build/draw/post-whole.pcdump.txt",
    }


def _draw_post_source_context_terminal_discovery_payload(
    *,
    stale_next_dimension: bool = False,
) -> dict:
    payload = {
        "function": DRAW_FUNCTION,
        "status": "unsupported-source-family",
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "terminal_reason": (
            "post-source-context-next-dimension/unsupported-source-family"
        ),
        "exhausted_source_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "exhausted_dimensions": [DRAW_POST_SOURCE_CONTEXT_DIMENSION],
        "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
        "unsupported_source_expression_class": DRAW_COUPLED_UNSUPPORTED_CLASS,
        "retained_evidence": [_draw_post_source_context_terminal_evidence_row()],
        "ranked_retained_c_probes": [_draw_post_source_context_terminal_evidence_row()],
        "source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "function": DRAW_SOURCE_FUNCTION,
                "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            }
        ],
    }
    if stale_next_dimension:
        payload["next_unsupported_source_dimension"] = (
            DRAW_POST_SOURCE_CONTEXT_DIMENSION
        )
    return payload


def _assert_draw_post_source_context_terminal_payload(payload: dict) -> None:
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
    )
    assert payload.get("next_unsupported_source_dimension") != (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    retained = synthesis_payload["retained_scored_probes"]
    assert {row["candidate_id"] for row in retained} >= {
        "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
    }
    best = next(
        row
        for row in retained
        if row["candidate_id"]
        == "draw-post-source-context-whole-function-joint-data-owner-with-loop-object"
    )
    assert best["target_score"]["matched"] == 1
    assert best["expression_score"]["matched"] == 1
    assert best["structural_guard"]["reason"] == "inline-boundary-toolchain-artifact"
    assert best["source_hunks"]
    assert DRAW_POST_SOURCE_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in synthesis_payload["exhausted_dimensions"]
    }


def _draw_post_source_context_written_candidates(
    tmp_path: Path,
) -> tuple[object, list[dict]]:
    context = _draw_post_source_context_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            include_source=True,
            max_per_dimension=8,
            validation_options={
                "expression_baseline": "build/diagnostics/current_retained.pcdump.txt",
                "checkdiff_guard": True,
            },
        ),
        tmp_path / "draw-post-source-context-probes",
    )
    return context, candidates


def _draw_post_all_known_source_context(
    tmp_path: Path,
) -> object:
    context, candidates = _draw_post_source_context_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
            accepted=False,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)
    terminal = classify_source_family_scores(candidates, scores, context)
    return normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )


def _draw_post_all_known_written_candidates(
    tmp_path: Path,
) -> tuple[object, list[dict]]:
    context = _draw_post_all_known_source_context(tmp_path)
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            include_source=True,
            max_per_dimension=8,
            validation_options={
                "expression_baseline": "build/diagnostics/current_retained.pcdump.txt",
                "checkdiff_guard": True,
            },
        ),
        tmp_path / "draw-post-all-known-probes",
    )
    return context, candidates


def _draw_product_translate_expression_graph_context(
    tmp_path: Path,
) -> object:
    context, candidates = _draw_post_all_known_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
            accepted=False,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)
    terminal = classify_source_family_scores(candidates, scores, context)
    terminal["source_spans"] = [
        *terminal.get("source_spans", []),
        {
            "source_file": "src/melee/mn/mndiagram.c",
            "source_line": 2601,
            "name": "translate_x",
            "expression": "(x_spacing * (f32) i) + col_offset",
            "dimension_id": DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
        },
        {
            "source_file": "src/melee/mn/mndiagram.c",
            "source_line": 2588,
            "name": "col_offset",
            "expression": "col product owner",
            "dimension_id": DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
        },
        {
            "source_file": "src/melee/mn/mndiagram.c",
            "source_line": 2589,
            "name": "row_offset",
            "expression": "row product owner",
            "dimension_id": DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
        },
    ]
    return normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )


def _draw_stack_clean_no_anchor_candidate(
    tmp_path: Path,
    candidate_id: str = (
        "draw-post-all-known-product-translate-graph-col-product-before-row-delta-with-y-offset"
    ),
) -> dict:
    return {
        "candidate_id": candidate_id,
        "dimension_id": DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
        "equivalence_class": DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
        "variant_id": candidate_id.rsplit("-", 1)[-1],
        "candidate_path": str(tmp_path / f"{candidate_id}.c"),
        "source_hunks": [
            {
                "hunk_id": "stack-clean-seed",
                "base_start": 2588,
                "base_end": 2604,
            }
        ],
        "source_components": [{"component_id": "draw-product-translate-seed"}],
        "validation_metadata": {
            "post_all_known_product_translate_expression_graph": True,
        },
    }


def _draw_stack_clean_no_anchor_score(
    candidate: dict,
    *,
    accepted: bool = False,
    classification: str = "stack-layout",
    normalized_diff_lines: int = 0,
    opcode_similarity: float = 1.0,
    expected_frame: int = 168,
    current_frame: int = 176,
    frame_delta: int = 8,
    source_retained: str | None = None,
    pcdump_path: str | None = "build/stack-clean-seed.pcdump.txt",
) -> dict:
    score = _draw_score(
        candidate,
        actual32=26,
        actual37=28,
        actual46=2,
        expression_actual32=26,
        expression_actual37=28,
        expression_actual46=2,
        accepted=accepted,
    )
    score["source_retained"] = source_retained or candidate["candidate_path"]
    if pcdump_path is not None:
        score["pcdump_path"] = pcdump_path
    score["structural_guard"] = {
        "accepted": accepted,
        "classification_primary": classification,
        "normalized_diff_lines": normalized_diff_lines,
        "opcode_similarity": opcode_similarity,
        "expected_frame": expected_frame,
        "current_frame": current_frame,
        "frame_delta": frame_delta,
    }
    return score


def _draw_stack_clean_seed_source() -> str:
    return (
        _draw_source()
        .replace(
            "    f32 row_offset;\n    f32 col_offset;\n    u8 col = arg1;\n",
            "    f32 row_offset;\n"
            "    f32 y_offset_owner;\n"
            "    f32 rowf;\n"
            "    f32 col_offset;\n"
            "    f32 col_product_owner;\n"
            "    u8 col = arg1;\n",
        )
        .replace(
            "    col_offset = y_spacing * (f32) col;\n    row_offset = y_offset * (f32) row;\n",
            "    col_product_owner = (f32) col;\n"
            "    col_product_owner *= y_spacing;\n"
            "    col_offset = col_product_owner;\n"
            "    y_offset_owner = y_offset;\n"
            "    row_offset = y_offset_owner * (f32) row;\n",
        )
    )


def _draw_stack_clean_actionable_frontier_payload(
    candidate: dict,
    score: dict,
    *,
    seed_path: Path,
) -> dict:
    ranked_recovery_probes = [
        {
            "rank": index,
            "probe_id": probe_id,
            "seed_candidate_id": candidate["candidate_id"],
            "source_retained": str(seed_path),
            "pcdump_path": score["pcdump_path"],
            "goal": f"goal {probe_id}",
        }
        for index, probe_id in enumerate(
            [
                "row-delta-anchor-local",
                "digit-fsubs-anchor-temp",
                "col-product-anchor-owner-transfer",
                "frame-clean-owner-prune",
            ],
            start=1,
        )
    ]
    continuation = {
        "route": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "dimension": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "seed_candidate_id": candidate["candidate_id"],
        "source_retained": str(seed_path),
        "pcdump_path": score["pcdump_path"],
        "source_hunks": candidate["source_hunks"],
        "source_components": candidate["source_components"],
        "target_score": score["target_score"],
        "expression_score": score["expression_score"],
        "stack_frame_facts": {
            "expected_frame": 168,
            "current_frame": 176,
            "frame_delta": 8,
            "normalized_diff_lines": 0,
            "opcode_similarity": 1.0,
        },
        "ranked_recovery_probes": ranked_recovery_probes,
    }
    frontier = {
        "kind": "post-meta-source-family-continuation-proof",
        "status": "source-actionable",
        "function": DRAW_FUNCTION,
        "family_id": "post-meta-source-family-continuation-proof",
        "continuation_family_id": "post-meta-source-family-continuation",
        "continuation": continuation,
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
        "attempted_targets": {"32": 28, "37": 26, "46": 26},
        "source_retained": str(seed_path),
        "pcdump_path": score["pcdump_path"],
        "source_hunks": candidate["source_hunks"],
        "target_score": score["target_score"],
        "expression_score": score["expression_score"],
    }
    return {
        "status": "actionable",
        "meta_ceiling": {"next_frontier": frontier},
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "next_frontier": frontier,
            }
        ],
    }


def _draw_stack_clean_failed_recovery_scores(candidates: list[dict]) -> list[dict]:
    return [
        {
            **_draw_score(
                candidate,
                actual32=26,
                actual37=28,
                actual46=2,
                expression_actual32=26,
                expression_actual37=28,
                expression_actual46=2,
                accepted=True,
            ),
            "source_retained": candidate.get("source_retained")
            or candidate.get("candidate_path"),
            "pcdump_path": f"build/{candidate['variant_id']}.pcdump.txt",
            "structural_guard": {
                "accepted": True,
                "classification_primary": "stack-layout",
                "normalized_diff_lines": 0,
                "opcode_similarity": 1.0,
                "expected_frame": 168,
                "current_frame": 176,
                "frame_delta": 8,
            },
        }
        for candidate in candidates
    ]


def _draw_stack_clean_final_context_and_seed(
    tmp_path: Path,
) -> tuple[object, str, Path]:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    seed_source = _draw_stack_clean_seed_source()
    seed_path = Path(candidate["candidate_path"])
    seed_path.write_text(seed_source, encoding="utf-8")
    score = _draw_stack_clean_no_anchor_score(
        candidate,
        source_retained=str(seed_path),
    )
    handoff = classify_source_family_scores([candidate], [score], context)
    replay_context = normalize_meta_ceiling_context(
        [handoff],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    generated = generate_source_family_candidates(
        seed_source,
        replay_context,
        max_per_dimension=8,
        include_source=True,
    )
    written = write_source_family_candidates(
        generated,
        tmp_path / "stack-clean-final-probes",
    )
    terminal = classify_source_family_scores(
        written,
        _draw_stack_clean_failed_recovery_scores(written),
        replay_context,
    )
    final_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    return final_context, seed_source, seed_path


def _draw_post_stack_source_shape_terminal_context_and_seed(
    tmp_path: Path,
) -> tuple[object, str, Path, list[dict]]:
    final_context, seed_source, seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )
    generated = generate_source_family_candidates(
        seed_source,
        final_context,
        max_per_dimension=8,
        include_source=True,
    )
    written = write_source_family_candidates(
        generated,
        tmp_path / "post-stack-source-shape-probes",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in written
    ]
    terminal = classify_source_family_scores(written, scores, final_context)
    post_stack_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    return post_stack_context, seed_source, seed_path, written


def _assert_draw_source_context_candidates(candidates: list[dict]) -> None:
    assert candidates
    assert 5 <= len(candidates) <= 6
    assert all(
        row["dimension_id"] == DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION
        for row in candidates
    )
    assert all(
        row["candidate_id"].startswith("draw-post-alt-source-context-")
        for row in candidates
    )
    assert not any(
        row["candidate_id"].startswith(
            (
                "draw-alternate-fpr-",
                "draw-coupled-fpr-",
                "post-meta-source-family-draw-expression-lifetime-",
            )
        )
        for row in candidates
    )
    component_ids = {
        component["component_id"]
        for row in candidates
        for component in row["source_components"]
    }
    assert {
        "draw-preloop-object-base-lifetime",
        "draw-loop-body-digit-callarg-animation",
        "draw-loop-body-translate-order",
        "draw-retained-baseline-backtracking",
    } <= component_ids
    for row in candidates:
        assert row["source_hunks"]
        assert row["source_components"]
        assert "debug target score-source" in row["score_source_command_hint"]
        metadata = row["validation_metadata"]
        assert metadata["post_alternate_source_context_lane"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["baseline_target_floor"] >= 1
        assert metadata["baseline_expression_floor"] >= 1
        assert metadata["source_components"] == row["source_components"]
        assert metadata["required_source_patterns"]


def _assert_draw_post_source_context_whole_function_candidates(
    candidates: list[dict],
) -> None:
    assert candidates
    assert 5 <= len(candidates) <= 6
    assert {row["dimension_id"] for row in candidates} == {
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith("draw-post-source-context-whole-function-")
        for row in candidates
    )
    old_dimensions = {
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
        DRAW_COUPLED_LIFETIME_DIMENSION,
        DRAW_ALTERNATE_DIMENSION,
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
    }
    assert not ({row["dimension_id"] for row in candidates} & old_dimensions)
    for row in candidates:
        component_ids = {
            component["component_id"] for component in row["source_components"]
        }
        assert component_ids & {
            "draw-preloop-data-owner",
            "draw-preloop-jobjs-owner",
            "draw-preloop-jobj-base-spacing-owner",
        }
        assert component_ids & {
            "draw-loop-joint-data-owner",
            "draw-loop-digit-jobj-owner",
            "draw-loop-animation-callarg-owner",
            "draw-loop-translate-owner",
            "draw-loop-add-child-parent-owner",
        }
        assert row["source_hunks"]
        assert row["source_components"]
        metadata = row["validation_metadata"]
        assert metadata["post_source_context_whole_function_fpr_source_model"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["final_force_phys"] == {"32": 28, "37": 26, "46": 26}
        assert metadata["baseline_target_floor"] == 1
        assert metadata["baseline_expression_floor"] == 1
        assert metadata["source_components"] == row["source_components"]
        assert metadata["required_source_patterns"]


def _draw_post_source_context_expected_candidate_ids() -> set[str]:
    return {
        "draw-post-source-context-whole-function-data-jobjs-parent-and-loop-object-owners",
        "draw-post-source-context-whole-function-base-spacing-owner-record",
        "draw-post-source-context-whole-function-joint-data-owner-with-loop-object",
        "draw-post-source-context-whole-function-animation-callarg-translate-owner",
        "draw-post-source-context-whole-function-parent-addchild-translate-owner",
        "draw-post-source-context-whole-function-whole-function-combined-low-risk",
    }


def _remove_draw_source_context_markers(raw) -> None:
    if isinstance(raw, dict):
        raw.pop("next_unsupported_source_spans", None)
        raw.pop("unsupported_source_dimension", None)
        for blocker in raw.get("generation_blockers", []) or []:
            if isinstance(blocker, dict):
                blocker.pop("unsupported_source_dimension", None)
        for value in raw.values():
            _remove_draw_source_context_markers(value)
    elif isinstance(raw, list):
        for value in raw:
            _remove_draw_source_context_markers(value)


def test_draw_alternate_floor_only_scores_emit_terminal_proof(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    scores = [
        _draw_floor_score(row, pcdump_path=f"build/{row['candidate_id']}.pcdump.txt")
        for row in candidates
    ]

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        "draw-alternate-fpr-expression-structure-exhausted/no-floor-improvement"
    )
    assert payload["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert payload["next_unsupported_source_model"] == DRAW_ALTERNATE_TERMINAL_MODEL
    assert {blocker["reason"] for blocker in payload["terminal_blockers"]} == {
        DRAW_ALTERNATE_TERMINAL_BLOCKER
    }
    assert DRAW_ALTERNATE_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    assert synthesis_payload["next_unsupported_source_family"] == (
        DRAW_ALTERNATE_TERMINAL_FAMILY
    )
    assert (
        DRAW_ALTERNATE_DIMENSION in synthesis_payload["attempted_equivalence_classes"]
    )
    retained = synthesis_payload["retained_scored_probes"]
    assert len(retained) == len(candidates)
    assert all(row["target_matched"] == 1 for row in retained)
    assert all(row["expression_matched"] == 1 for row in retained)
    assert all(row["pcdump_path"] for row in retained)
    assert all(row["target_score"] for row in retained)
    assert all(row["expression_score"] for row in retained)
    assert all(row["structural_guard"] for row in retained)
    assert all(row["source_hunks"] for row in retained)
    assert all(row["source_components"] for row in retained)


def test_draw_post_alternate_zero_candidates_emit_terminal_proof_with_real_evidence(
    tmp_path: Path,
) -> None:
    terminal, payload, candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path)
    )
    terminal_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    assert (
        generate_source_family_candidates(
            _draw_source(),
            terminal_context,
            include_source=True,
        )
        == []
    )
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["scored_count"] == len(candidates)
    assert payload["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert payload["candidate_scores"]
    assert payload["retained_scored_probes"]
    assert payload["source_hunks_by_candidate"]

    for retained in payload["retained_scored_probes"]:
        assert retained["source_retained"]
        assert retained["pcdump_path"]
        assert retained["target_score"]
        assert retained["expression_score"]
        assert retained["source_hunks"]
        assert retained["structural_guard"]

    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert DRAW_ALTERNATE_DIMENSION in payload["attempted_equivalence_classes"]
    assert DRAW_ALTERNATE_DIMENSION in proof["attempted_equivalence_classes"]
    assert (
        DRAW_ALTERNATE_DIMENSION in synthesis_payload["attempted_equivalence_classes"]
    )
    assert DRAW_ALTERNATE_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    assert DRAW_ALTERNATE_DIMENSION in {
        row["dimension_id"] for row in synthesis_payload["exhausted_dimensions"]
    }
    blocker_reasons = {
        value
        for row in payload["terminal_blockers"]
        for value in (row["reason"], row["terminal_blocker"])
    }
    assert DRAW_ALTERNATE_TERMINAL_BLOCKER in blocker_reasons
    assert DRAW_POST_ALTERNATE_TERMINAL_BLOCKER in blocker_reasons
    assert payload["generation_blockers"][0]["terminal_blocker"] == (
        DRAW_POST_ALTERNATE_TERMINAL_BLOCKER
    )

    span_names = {row["name"] for row in payload["next_unsupported_source_spans"]}
    assert {
        "draw-preloop-object-base-lifetime-source-context",
        "draw-loop-body-callarg-translate-interaction-source-context",
        "draw-retained-baseline-backtracking-source-context",
    } <= span_names
    assert (
        synthesis_payload["next_unsupported_source_spans"]
        == (payload["next_unsupported_source_spans"])
    )
    assert payload["available_candidate_count"] == len(DRAW_ALTERNATE_CANDIDATE_IDS)
    assert payload["generated_candidate_count"] == len(candidates)
    assert payload["scored_candidate_count"] == len(candidates)
    assert set(payload["available_candidate_ids"]) == DRAW_ALTERNATE_CANDIDATE_IDS
    assert set(payload["generated_candidate_ids"]) == {
        row["candidate_id"] for row in candidates
    }
    assert set(payload["scored_candidate_ids"]) == {
        row["candidate_id"] for row in candidates
    }
    assert payload["unscored_candidate_ids"] == []
    assert synthesis_payload["available_candidate_count"] == len(
        DRAW_ALTERNATE_CANDIDATE_IDS
    )
    assert synthesis_payload["generated_candidate_count"] == len(candidates)
    assert synthesis_payload["scored_candidate_count"] == len(candidates)


def test_draw_post_alternate_sentinel_without_retained_score_evidence_is_not_terminal(
    tmp_path: Path,
) -> None:
    terminal, _payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path)
    )
    terminal["candidate_scores"] = []
    terminal["retained_scored_probes"] = []
    terminal["source_hunks_by_candidate"] = []
    proof = terminal["source_model_proof"]
    proof["candidate_scores"] = []
    proof["retained_scored_probes"] = []
    proof["source_hunks_by_candidate"] = []
    synthesis_payload = proof["source_family_synthesis"]
    synthesis_payload["candidate_scores"] = []
    synthesis_payload["retained_scored_probes"] = []
    synthesis_payload["source_hunks_by_candidate"] = []
    context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    payload = build_generated_source_family_payload([], context)

    assert payload["status"] != "terminal"
    assert DRAW_POST_ALTERNATE_TERMINAL_BLOCKER not in {
        blocker.get("terminal_blocker")
        for blocker in payload.get("generation_blockers", [])
        if isinstance(blocker, dict)
    }


def test_draw_post_alternate_retained_progress_without_no_floor_is_not_terminal(
    tmp_path: Path,
) -> None:
    terminal, _payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path)
    )
    proof = terminal["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    for container in (terminal, proof, synthesis_payload):
        container["terminal_blockers"] = []
        for key in ("candidate_scores", "retained_scored_probes"):
            for row in container.get(key) or []:
                row["target_matched"] = 2
                row["target_score"]["matched"] = 2
                row["target_score"]["virtual_distance"] = 1
    context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    payload = build_generated_source_family_payload([], context)

    assert payload["status"] != "terminal"
    assert DRAW_POST_ALTERNATE_TERMINAL_BLOCKER not in {
        blocker.get("terminal_blocker")
        for blocker in payload.get("generation_blockers", [])
        if isinstance(blocker, dict)
    }


def test_draw_post_alternate_terminal_replay_records_capped_alternate_family(
    tmp_path: Path,
) -> None:
    _terminal, payload, candidates, retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path, retained_count=6)
    )
    retained_ids = {row["candidate_id"] for row in retained_candidates}

    assert payload["status"] == "terminal"
    assert payload["available_candidate_count"] == len(DRAW_ALTERNATE_CANDIDATE_IDS)
    assert payload["generated_candidate_count"] == len(retained_candidates)
    assert payload["scored_candidate_count"] == len(retained_candidates)
    assert set(payload["available_candidate_ids"]) == DRAW_ALTERNATE_CANDIDATE_IDS
    assert set(payload["generated_candidate_ids"]) == retained_ids
    assert set(payload["scored_candidate_ids"]) == retained_ids
    assert set(payload["unscored_candidate_ids"]) == (
        DRAW_ALTERNATE_CANDIDATE_IDS - retained_ids
    )
    assert len(candidates) == len(DRAW_ALTERNATE_CANDIDATE_IDS)
    assert payload["generation_blockers"][0]["terminal_blocker"] == (
        DRAW_POST_ALTERNATE_TERMINAL_BLOCKER
    )
    assert payload["generation_blockers"][0]["reason"] == (
        DRAW_ALTERNATE_TERMINAL_FAMILY
    )


def test_cli_source_model_synthesis_replays_draw_post_alternate_terminal(
    tmp_path: Path,
) -> None:
    terminal, _payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path, retained_count=6)
    )
    meta = tmp_path / "draw-alternate-terminal.json"
    meta.write_text(json.dumps(terminal), encoding="utf-8")
    source = tmp_path / "draw.c"
    source.write_text(_draw_live_retained_split_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["retained_scored_probes"]
    assert payload["next_unsupported_source_spans"]


def test_draw_post_alternate_terminal_replay_reaches_retained_allocator(
    tmp_path: Path,
) -> None:
    _terminal, payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path, retained_count=6)
    )
    artifact = tmp_path / "draw-post-alternate-terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    function = triaged["functions"][0]
    assert function["meta_ceiling"]["status"] == "terminal-current-source-shape-ceiling"
    proof = function["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert proof["next_unsupported_source_spans"]
    assert result["status"] == "practical-ceiling"
    assert any(DRAW_ALTERNATE_TERMINAL_MODEL in step for step in result["next_steps"])
    assert any(DRAW_ALTERNATE_TERMINAL_FAMILY in step for step in result["next_steps"])
    rendered = render_allocator_ceiling_text(result)
    assert "next unsupported source spans" in rendered
    assert "draw-loop-body-callsite-and-object-base-lifetime-source-context" in rendered


def test_draw_alternate_rejected_below_floor_scores_still_terminalize(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    scores = [_draw_score(row, accepted=False) for row in candidates]

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert {blocker["reason"] for blocker in payload["terminal_blockers"]} == {
        DRAW_ALTERNATE_TERMINAL_BLOCKER,
        "structural-guard-not-accepted",
    }
    retained = payload["source_model_proof"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    assert all(row["target_matched"] == 0 for row in retained)
    assert all(row["expression_matched"] == 0 for row in retained)
    assert all(row["structural_guard_accepted"] is False for row in retained)


def test_draw_post_alternate_terminal_generates_source_context_lane_for_split_source(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)

    candidates = generate_source_family_candidates(
        _draw_split_source(),
        context,
        include_source=True,
    )

    _assert_draw_source_context_candidates(candidates)
    assert any("HSD_JObj** jobjs" in row["source_text"] for row in candidates)
    assert any("HSD_JObj* parent" in row["source_text"] for row in candidates)
    assert any("translate_x" in row["source_text"] for row in candidates)


def test_draw_post_alternate_terminal_generates_source_context_lane_for_legacy_source(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        include_source=True,
    )

    _assert_draw_source_context_candidates(candidates)
    assert any("y_offset" in row["source_text"] for row in candidates)


def test_draw_post_alternate_source_context_legacy_source_preserves_loop_inputs(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)
    source_text = _draw_source()
    original_span = (
        synthesis.find_function(source_text, "mnDiagram_DrawCellValue")
        or synthesis.find_function(source_text, "mnDiagram_DrawCellNumber")
        or synthesis.find_function(source_text, "mnDiagram_80241E78")
    )
    assert original_span is not None
    original_function = source_text[original_span.sig_start : original_span.full_end]
    digit_arg = "value" if "mn_GetDigitAt(value, i)" in original_function else "arg3"
    load_arg = (
        "joint_data->joint"
        if "HSD_JObjLoadJoint(joint_data->joint)" in original_function
        else "joint_data[0]"
    )
    anim_args = (
        (
            "joint_data->anim_joint",
            "joint_data->mat_anim",
            "joint_data->shape_anim",
        )
        if "joint_data->anim_joint" in original_function
        else ("joint_data[1]", "joint_data[2]", "joint_data[3]")
    )

    candidates = generate_source_family_candidates(
        source_text,
        context,
        include_source=True,
    )

    by_id = {row["candidate_id"]: row for row in candidates}
    for candidate_id in {
        "draw-post-alt-source-context-loop-digit-jobj-local",
        "draw-post-alt-source-context-loop-translate-locals",
        "draw-post-alt-source-context-combined-lower-hill-backtrack",
    }:
        source_text = by_id[candidate_id]["source_text"]
        span = (
            synthesis.find_function(source_text, "mnDiagram_DrawCellValue")
            or synthesis.find_function(source_text, "mnDiagram_DrawCellNumber")
            or synthesis.find_function(source_text, "mnDiagram_80241E78")
        )
        assert span is not None
        function_text = source_text[span.sig_start : span.full_end]
        assert f"mn_GetDigitAt({digit_arg}, i)" in function_text
        assert f"HSD_JObjLoadJoint({load_arg})" in function_text
        for arg in anim_args:
            assert arg in function_text


def test_draw_post_alternate_current_source_alias_resolves(tmp_path: Path) -> None:
    source_path = (
        Path(__file__).resolve().parents[3] / "src/melee/mn/mndiagram.c"
    )
    context = _draw_post_alternate_source_context(tmp_path)

    resolved = synthesis.resolve_source_function_context(
        source_path.read_text(encoding="utf-8"),
        context,
    )

    assert resolved.source_function == "mnDiagram_DrawCellValue"


def test_draw_post_alternate_source_context_requires_exact_dimension_marker(
    tmp_path: Path,
) -> None:
    terminal, payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path, retained_count=6)
    )
    raw_terminal_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    assert (
        generate_source_family_candidates(
            _draw_source(),
            raw_terminal_context,
            include_source=True,
        )
        == []
    )

    stripped = json.loads(json.dumps(payload))
    _remove_draw_source_context_markers(stripped)
    stripped_context = normalize_meta_ceiling_context(
        [stripped],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    assert (
        generate_source_family_candidates(
            _draw_source(),
            stripped_context,
            include_source=True,
        )
        == []
    )

    marked = json.loads(json.dumps(stripped))
    marked["generation_blockers"][0]["unsupported_source_dimension"] = (
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION
    )
    marked_context = normalize_meta_ceiling_context(
        [marked],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    candidates = generate_source_family_candidates(
        _draw_source(),
        marked_context,
        include_source=True,
    )
    _assert_draw_source_context_candidates(candidates)


def test_cli_source_model_synthesis_writes_draw_source_context_probes(
    tmp_path: Path,
) -> None:
    _terminal, payload, _candidates, _retained_candidates = (
        _draw_alternate_terminal_replay_payload(tmp_path, retained_count=6)
    )
    meta = tmp_path / "draw-post-alternate-terminal.json"
    meta.write_text(json.dumps(payload), encoding="utf-8")
    source = tmp_path / "draw.c"
    source.write_text(_draw_split_source(), encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    baseline = tmp_path / "baseline.pcdump.txt"
    baseline.write_text("", encoding="utf-8")
    output = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(output),
            "--target",
            str(target),
            "--expression-baseline",
            str(baseline),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    generated = json.loads(result.output)
    assert generated["status"] == "generated"
    _assert_draw_source_context_candidates(generated["candidates"])
    for row in generated["candidates"]:
        candidate_path = Path(row["candidate_path"])
        assert candidate_path.exists()
        assert row["source_retained"] == str(candidate_path)
        assert row["source_hunks"]
        assert row["source_components"]
        assert "debug target score-source" in row["score_source_command_hint"]
        assert row["score_command"] == row["score_source_command_hint"]
        assert "--expression-reg-class fpr" in row["score_command"]
        assert "--retain-pcdump" in row["score_command"]
        assert "--checkdiff-guard" in row["score_command"]
        assert "--full-unit-source" not in row["score_command"]


def test_draw_post_source_context_whole_function_live_retained_split_region_ready() -> (
    None
):
    source = _draw_live_retained_split_source()
    span = synthesis.find_function(source, DRAW_FUNCTION)
    assert span is not None
    function_text = source[span.sig_start : span.full_end]

    ready, missing = synthesis._draw_post_source_context_whole_function_region_ready(
        function_text
    )

    assert ready is True
    assert missing == []
    required_patterns = synthesis.DRAW_POST_SOURCE_CONTEXT_REQUIRED_SOURCE_PATTERNS
    assert any("retained row_offset/rowf split" in item for item in required_patterns)
    assert not any(
        "x_spacing, y_spacing, y_offset, col_offset" in item
        for item in required_patterns
    )


def test_draw_post_source_context_whole_function_live_retained_split_generates_candidates() -> (
    None
):
    context = _draw_post_source_context_context()

    candidates = generate_source_family_candidates(
        _draw_live_retained_split_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert {row["candidate_id"] for row in candidates} == (
        _draw_post_source_context_expected_candidate_ids()
    )
    assert {row["dimension_id"] for row in candidates} == {
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    }
    for row in candidates:
        assert row["source_hunks"]
        assert row["source_components"]
        metadata = row["validation_metadata"]
        assert metadata["required_source_patterns"]
        assert metadata["post_source_context_whole_function_fpr_source_model"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_structural_guard"] is True

    by_id = {row["candidate_id"]: row for row in candidates}
    for candidate_id in {
        "draw-post-source-context-whole-function-joint-data-owner-with-loop-object",
        "draw-post-source-context-whole-function-whole-function-combined-low-risk",
    }:
        source_text = by_id[candidate_id]["source_text"]
        object_name = (
            "digit_jobj"
            if candidate_id.endswith("joint-data-owner-with-loop-object")
            else "jobj"
        )
        assert "digit_joint = joint_data->joint;" in source_text
        assert "digit_anim_joint = joint_data->anim_joint;" in source_text
        assert "digit_matanim_joint = joint_data->mat_anim;" in source_text
        assert "digit_shapeanim_joint = joint_data->shape_anim;" in source_text
        assert "HSD_JObjLoadJoint(digit_joint)" in source_text
        assert (
            f"HSD_JObjAddAnimAll({object_name}, digit_anim_joint, digit_matanim_joint, digit_shapeanim_joint)"
        ) in source_text


def test_draw_post_source_context_whole_function_stage_generates_only_new_dimension() -> (
    None
):
    context = _draw_post_source_context_context()

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    _assert_draw_post_source_context_whole_function_candidates(candidates)


def test_draw_post_source_context_whole_function_score_hints_preserve_floors_and_baseline() -> (
    None
):
    context = _draw_post_source_context_context()

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
        validation_options={
            "expression_baseline": "build/diagnostics/current_retained.pcdump.txt",
            "checkdiff_guard": True,
        },
    )

    _assert_draw_post_source_context_whole_function_candidates(candidates)
    for row in candidates:
        metadata = row["validation_metadata"]
        assert metadata["target_expression_validation"] == {
            "requires_target_score_validation": True,
            "requires_expression_score_validation": True,
            "baseline_target_floor": 1,
            "baseline_expression_floor": 1,
            "real_expression_progress_required": True,
        }
        assert (
            "--expression-baseline build/diagnostics/current_retained.pcdump.txt"
            in metadata["score_source_command_hint"]
        )


def test_draw_post_source_context_whole_function_zero_candidate_missing_pattern_blocks_dimension() -> (
    None
):
    context = _draw_post_source_context_context()
    source = _draw_source().replace(
        "    joint_data = mnDiagram_804A07F4;\n",
        "",
    )
    candidates = generate_source_family_candidates(
        source,
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert not any(
        row["dimension_id"]
        == SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        for row in candidates
    )
    payload = build_generated_source_family_payload(candidates, context)
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    blocked = payload["blocked_dimensions"]
    assert blocked
    assert blocked[0]["dimension_id"] == DRAW_POST_SOURCE_CONTEXT_DIMENSION
    assert blocked[0]["blockers"][0]["reason"] == (
        DRAW_POST_SOURCE_CONTEXT_PATTERN_BLOCKER
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )


def test_draw_post_source_context_whole_function_terminal_ignores_renumbering_only_expression_progress(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_post_source_context_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        "draw-post-source-context-whole-function-fpr-source-model-exhausted/no-floor-improvement"
    )
    assert {blocker["reason"] for blocker in payload["terminal_blockers"]} == {
        DRAW_POST_SOURCE_CONTEXT_NO_FLOOR_BLOCKER
    }
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    retained = synthesis_payload["retained_scored_probes"]
    assert retained
    assert all(row["target_score"] for row in retained)
    assert all(row["expression_score"] for row in retained)
    assert all(row["pcdump_path"] for row in retained)
    assert all(row["source_hunks"] for row in retained)
    assert all(row["source_components"] for row in retained)
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
    )


def test_draw_post_source_context_whole_function_target_progress_remains_actionable(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_post_source_context_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            actual37=26,
            expression_actual32=28,
            expression_actual37=26,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    best = payload["best_candidate"]
    assert best["target_matched"] > 1
    assert best["target_score"]
    assert best["expression_score"]
    assert best["pcdump_path"]
    assert best["source_hunks"]
    assert best["source_components"]


def test_cli_source_model_synthesis_materializes_draw_post_source_context_handoff(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "draw-post-source-context-handoff.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-post-source-context-out"
    meta.write_text(
        json.dumps(_draw_post_source_context_handoff_payload()),
        encoding="utf-8",
    )
    source.write_text(_draw_live_retained_split_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--max-per-dimension",
            "8",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] == 6
    assert {row["candidate_id"] for row in payload["candidates"]} == (
        _draw_post_source_context_expected_candidate_ids()
    )
    assert {row["dimension_id"] for row in payload["candidates"]} == {
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    }
    assert {row["dimension_id"] for row in payload["dimensions"]} == {
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    }
    blocked = payload.get("blocked_dimensions") or []
    assert not any(
        row.get("dimension_id") == DRAW_POST_SOURCE_CONTEXT_DIMENSION
        and any(
            blocker.get("reason") == DRAW_POST_SOURCE_CONTEXT_PATTERN_BLOCKER
            for blocker in row.get("blockers", [])
        )
        for row in blocked
    )
    assert all(Path(row["candidate_path"]).is_file() for row in payload["candidates"])
    assert all(row["source_hunks"] for row in payload["candidates"])
    assert all(row["source_components"] for row in payload["candidates"])


def test_draw_post_source_context_terminal_discovery_suppresses_whole_function_generation() -> (
    None
):
    context = normalize_meta_ceiling_context(
        [_draw_post_source_context_terminal_discovery_payload()],
        function=DRAW_FUNCTION,
        repo_root=Path.cwd(),
    )

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert not any(
        row["dimension_id"]
        == SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        for row in candidates
    )
    payload = build_generated_source_family_payload(candidates, context)
    _assert_draw_post_source_context_terminal_payload(payload)


def test_draw_post_source_context_retained_aggregate_suppresses_stale_dimension() -> (
    None
):
    aggregate = {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "terminal_frontiers": [
                    {
                        "function": DRAW_FUNCTION,
                        "terminal": True,
                        "family_id": "post-source-context-fpr-ceiling-next-dimension",
                        "source_model_proof": (
                            _draw_post_source_context_terminal_discovery_payload(
                                stale_next_dimension=True
                            )
                        ),
                    }
                ],
                "meta_ceiling": {
                    "terminal_proof": _draw_post_source_context_handoff_payload()[
                        "current_ceiling"
                    ]
                },
            }
        ],
    }
    context = normalize_meta_ceiling_context(
        [aggregate],
        function=DRAW_FUNCTION,
        repo_root=Path.cwd(),
    )

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert candidates == []
    payload = build_generated_source_family_payload(candidates, context)
    _assert_draw_post_source_context_terminal_payload(payload)


def test_cli_source_model_synthesis_terminal_suppression_writes_no_whole_function_probes(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "draw-post-source-context-terminal.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-terminal-out"
    meta.write_text(
        json.dumps(
            _draw_post_source_context_terminal_discovery_payload(
                stale_next_dimension=True
            )
        ),
        encoding="utf-8",
    )
    source.write_text(_draw_live_retained_split_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--max-per-dimension",
            "8",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    _assert_draw_post_source_context_terminal_payload(payload)
    assert not list(out_dir.glob("draw-post-source-context-whole-function-*.c"))


def test_retained_frontiers_prefers_draw_post_source_context_terminal_over_handoff(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_post_source_context_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)
    terminal = classify_source_family_scores(candidates, scores, context)
    handoff_artifact = tmp_path / "draw-post-source-context-handoff.json"
    terminal_artifact = tmp_path / "draw-post-source-context-terminal.json"
    handoff_artifact.write_text(
        json.dumps(_draw_post_source_context_handoff_payload()),
        encoding="utf-8",
    )
    terminal_artifact.write_text(json.dumps(terminal), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[handoff_artifact, terminal_artifact],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert DRAW_POST_SOURCE_CONTEXT_DIMENSION in proof["attempted_equivalence_classes"]
    assert result["status"] == "practical-ceiling"
    assert any(
        DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL in step for step in result["next_steps"]
    )


def test_draw_post_all_known_generates_candidates_after_whole_function_terminal(
    tmp_path: Path,
) -> None:
    context = _draw_post_all_known_source_context(tmp_path)

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert candidates
    assert {row["dimension_id"] for row in candidates} == {
        DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
    }
    assert not any(
        row["candidate_id"].startswith("draw-post-source-context-whole-function-")
        for row in candidates
    )
    for row in candidates:
        assert row["source_hunks"]
        assert row["source_components"]
        metadata = row["validation_metadata"]
        assert metadata["post_all_known_source_context_hypothesis"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["baseline_target_floor"] == 1
        assert metadata["baseline_expression_floor"] >= 1


def test_draw_post_all_known_structural_guard_progress_is_actionable(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_post_all_known_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
            accepted=True,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    best = payload["best_candidate"]
    assert best["dimension_id"] == DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
    assert best["target_matched"] == 1
    assert best["expression_score"]["real_matched"] == 1
    assert best["structural_guard"]["accepted"] is True
    assert best["source_hunks"]
    assert best["pcdump_path"]

    artifact = tmp_path / "draw-post-all-known-actionable.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    frontier = triaged["functions"][0]["frontiers"][0]
    assert frontier["dimension_id"] == DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
    assert result["status"] == "actionable"
    assert result["next_frontier"]["dimension_id"] == (
        DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION
    )


def test_draw_post_all_known_terminal_replay_suppresses_repeat_generation(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_post_all_known_written_candidates(tmp_path)
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
            accepted=False,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)
    terminal = classify_source_family_scores(candidates, scores, context)
    terminal_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    repeat_candidates = generate_source_family_candidates(
        _draw_source(),
        terminal_context,
        max_per_dimension=8,
        include_source=True,
    )
    repeat_payload = build_generated_source_family_payload(
        repeat_candidates,
        terminal_context,
    )

    assert repeat_candidates == []
    assert repeat_payload["status"] == "terminal"
    assert repeat_payload["candidate_count"] == 0
    assert repeat_payload["next_unsupported_source_family"] == (
        DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert DRAW_POST_ALL_KNOWN_SOURCE_CONTEXT_DIMENSION in {
        row["dimension_id"]
        for row in repeat_payload["source_model_proof"]["source_family_synthesis"][
            "exhausted_dimensions"
        ]
    }

    meta = tmp_path / "draw-post-all-known-terminal.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-post-all-known-repeat-out"
    meta.write_text(json.dumps(terminal), encoding="utf-8")
    source.write_text(_draw_source(), encoding="utf-8")
    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--max-per-dimension",
            "8",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["candidate_count"] == 0
    assert not list(out_dir.glob("draw-post-all-known-source-context-*.c"))
    assert not list(out_dir.glob("draw-post-source-context-whole-function-*.c"))


def test_draw_product_translate_generates_bounded_candidates_after_post_all_known_terminal(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)

    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert len(candidates) == 4
    assert {row["dimension_id"] for row in candidates} == {
        DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith("draw-post-all-known-product-translate-graph-")
        for row in candidates
    )
    assert not any(
        row["candidate_id"].startswith("draw-post-all-known-source-context-")
        for row in candidates
    )
    for row in candidates:
        metadata = row["validation_metadata"]
        assert metadata["post_all_known_product_translate_expression_graph"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["baseline_target_floor"] >= 1
        assert metadata["baseline_expression_floor"] >= 1
        assert row["source_hunks"]
        assert row["source_components"]


def test_draw_product_translate_generated_payload_ignores_stale_terminal_blockers(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidates = generate_source_family_candidates(
        _draw_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    payload = build_generated_source_family_payload(candidates, context)

    assert payload["status"] == "generated"
    assert payload["candidate_count"] == 4
    assert payload.get("terminal_reason") is None
    assert payload.get("generation_blockers") is None
    assert payload["dimensions"] == [
        {
            "dimension_id": DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION,
            "generated_candidate_ids": [row["candidate_id"] for row in candidates],
            "scored_candidate_ids": [],
            "candidate_count": 4,
            "scored_count": 0,
        }
    ]


def test_draw_product_translate_supports_retained_split_source_spelling(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)

    candidates = generate_source_family_candidates(
        _draw_split_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    assert len(candidates) == 4
    sources = {row["candidate_id"]: row["source_text"] for row in candidates}
    assert (
        "row_delta_product = row_offset;"
        in sources[
            "draw-post-all-known-product-translate-graph-row-delta-product-before-col-product"
        ]
    )
    assert (
        "y_offset_owner = y_offset;"
        in sources[
            "draw-post-all-known-product-translate-graph-col-product-before-row-delta-with-y-offset"
        ]
    )


def test_draw_product_translate_structural_guard_progress_is_actionable(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            include_source=True,
            max_per_dimension=8,
        ),
        tmp_path / "draw-product-translate-probes",
    )
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
            accepted=True,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["dimension_id"] == (
        DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION
    )
    assert payload["best_candidate"]["structural_guard"]["accepted"] is True


def test_draw_product_translate_terminal_replay_suppresses_post_all_known_handoff(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            include_source=True,
            max_per_dimension=8,
        ),
        tmp_path / "draw-product-translate-terminal-probes",
    )
    scores = []
    for row in candidates:
        score = _draw_score(
            row,
            actual32=28,
            expression_actual32=28,
            expression_actual37=26,
            accepted=False,
        )
        score["pcdump_path"] = f"build/{row['candidate_id']}.pcdump.txt"
        score["expression_score"]["renumbered"] = 1
        score["expression_score"]["real_matched"] = 1
        scores.append(score)
    terminal = classify_source_family_scores(candidates, scores, context)
    terminal_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    repeat_candidates = generate_source_family_candidates(
        _draw_source(),
        terminal_context,
        max_per_dimension=8,
        include_source=True,
    )
    repeat_payload = build_generated_source_family_payload(
        repeat_candidates,
        terminal_context,
    )

    assert repeat_candidates == []
    assert repeat_payload["status"] == "terminal"
    assert repeat_payload["next_unsupported_source_family"] == (
        DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY
    )
    assert repeat_payload["next_unsupported_source_model"] == (
        DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_MODEL
    )
    synthesis_payload = repeat_payload["source_model_proof"]["source_family_synthesis"]
    assert DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_DIMENSION in {
        row["dimension_id"] for row in synthesis_payload["exhausted_dimensions"]
    }
    blockers = synthesis_payload["terminal_blockers"]
    assert any(
        row["reason"] == DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_NO_FLOOR_BLOCKER
        for row in blockers
    )


def test_draw_product_translate_stack_clean_no_anchor_emits_recovery_handoff_before_final_ceiling(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    score = _draw_stack_clean_no_anchor_score(candidate)

    payload = classify_source_family_scores([candidate], [score], context)

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY
    )
    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert synthesis_payload["next_unsupported_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    evidence = proof["stack_clean_no_anchor_evidence"]
    assert synthesis_payload["stack_clean_no_anchor_evidence"] == evidence
    assert evidence["seed_candidate_id"] == candidate["candidate_id"]
    assert evidence["source_retained"] == candidate["candidate_path"]
    assert evidence["pcdump_path"] == "build/stack-clean-seed.pcdump.txt"
    assert evidence["source_hunks"] == candidate["source_hunks"]
    assert evidence["target_score"]["matched"] == 0
    assert evidence["expression_score"]["matched"] == 0
    assert evidence["stack_frame_facts"] == {
        "classification": "stack-layout",
        "expected_frame": 168,
        "current_frame": 176,
        "frame_delta": 8,
        "normalized_diff_lines": 0,
        "opcode_similarity": 1.0,
        "structural_guard_accepted": False,
    }
    target_facts = {row["virtual"]: row for row in evidence["target_virtual_facts"]}
    expression_facts = {
        row["virtual"]: row for row in evidence["expression_virtual_facts"]
    }
    assert {32, 37, 46} <= set(target_facts)
    assert {32, 37, 46} <= set(expression_facts)
    assert target_facts[32]["expected"] == 28
    assert target_facts[37]["actual"] == 28
    assert expression_facts[46]["actual"] == 2
    assert [row["probe_id"] for row in evidence["ranked_recovery_probes"]] == [
        "row-delta-anchor-local",
        "digit-fsubs-anchor-temp",
        "col-product-anchor-owner-transfer",
        "frame-clean-owner-prune",
    ]


def test_draw_stack_clean_next_dimension_replay_materializes_ranked_recovery_probes(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    seed_source = _draw_stack_clean_seed_source()
    seed_path = Path(candidate["candidate_path"])
    seed_path.write_text(seed_source, encoding="utf-8")
    score = _draw_stack_clean_no_anchor_score(
        candidate,
        source_retained=str(seed_path),
    )
    handoff = classify_source_family_scores([candidate], [score], context)
    replay_context = normalize_meta_ceiling_context(
        [handoff],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    generated = generate_source_family_candidates(
        seed_source,
        replay_context,
        max_per_dimension=8,
        include_source=True,
    )

    assert [row["variant_id"] for row in generated] == [
        "row-delta-anchor-local",
        "digit-fsubs-anchor-temp",
        "col-product-anchor-owner-transfer",
        "frame-clean-owner-prune",
    ]
    assert {row["dimension_id"] for row in generated} == {
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith(
            "draw-post-product-translate-stack-clean-no-anchor-"
        )
        for row in generated
    )
    assert not any(
        row["candidate_id"].startswith("draw-post-all-known-product-translate-graph-")
        for row in generated
    )
    for row in generated:
        metadata = row["validation_metadata"]
        assert metadata["stack_clean_no_anchor_recovery"] is True
        assert metadata["seed_source_retained"] == str(seed_path)
        assert metadata["seed_pcdump_path"] == "build/stack-clean-seed.pcdump.txt"
        assert metadata["seed_source_hunks"] == candidate["source_hunks"]
        assert metadata["seed_target_score"] == score["target_score"]
        assert metadata["seed_expression_score"] == score["expression_score"]
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert row["source_hunks"]
        assert row["source_text"] != seed_source
        assert any(
            component.get("component_id") == "draw-product-translate-seed"
            for component in row["source_components"]
        )
        assert any(
            component.get("recovery_goal") == row["variant_id"]
            for component in row["source_components"]
        )
    by_variant = {row["variant_id"]: row["source_text"] for row in generated}
    assert "rowf = (f32) row;" in by_variant["row-delta-anchor-local"]
    assert "digit_fsubs_anchor = (f32) digit;" in by_variant["digit-fsubs-anchor-temp"]
    assert (
        "col_product_anchor = col_product_owner;"
        in by_variant["col-product-anchor-owner-transfer"]
    )
    assert "y_offset_owner" not in by_variant["frame-clean-owner-prune"]

    written = write_source_family_candidates(
        generated,
        tmp_path / "stack-clean-probes",
        include_source=False,
    )
    assert all(Path(row["source_retained"]).exists() for row in written)
    payload = build_generated_source_family_payload(generated, replay_context)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] == 4
    assert {row["dimension_id"] for row in payload["dimensions"]} == {
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    }


def test_draw_stack_clean_actionable_frontier_aggregate_normalizes_to_recovery_context(
    tmp_path: Path,
) -> None:
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    seed_path = tmp_path / "retained-seed.c"
    seed_path.write_text(_draw_stack_clean_seed_source(), encoding="utf-8")
    score = _draw_stack_clean_no_anchor_score(candidate, source_retained=str(seed_path))
    aggregate = _draw_stack_clean_actionable_frontier_payload(
        candidate,
        score,
        seed_path=seed_path,
    )

    context = normalize_meta_ceiling_context(
        [aggregate],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    assert context.function == DRAW_FUNCTION
    assert context.next_unsupported_source_dimension == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert context.force_phys == {"32": 28, "37": 26, "46": 26}
    actuals = {row["virtual"]: row["actual"] for row in context.allocator_facts}
    assert actuals[32] == 26
    assert actuals[37] == 28
    assert actuals[46] == 2
    evidence = context.current_ceiling["source_model_proof"][
        "stack_clean_no_anchor_evidence"
    ]
    assert evidence["source_retained"] == str(seed_path)
    assert evidence["pcdump_path"] == "build/stack-clean-seed.pcdump.txt"


def test_cli_source_model_synthesis_writes_draw_stack_clean_recovery_probes(
    tmp_path: Path,
) -> None:
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    seed_path = tmp_path / "retained-seed.c"
    seed_path.write_text(_draw_stack_clean_seed_source(), encoding="utf-8")
    score = _draw_stack_clean_no_anchor_score(candidate, source_retained=str(seed_path))
    aggregate_path = tmp_path / "retained-frontiers.json"
    aggregate_path.write_text(
        json.dumps(
            _draw_stack_clean_actionable_frontier_payload(
                candidate,
                score,
                seed_path=seed_path,
            )
        ),
        encoding="utf-8",
    )
    output = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(aggregate_path),
            "--write-probes",
            str(output),
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] == 4
    written = sorted(path.name for path in output.glob("*.c"))
    assert len(written) == 4
    assert all(
        name.startswith("draw-post-product-translate-stack-clean-no-anchor-")
        for name in written
    )
    assert not any(
        name.startswith("draw-post-all-known-product-translate-graph-")
        for name in written
    )
    for row in payload["candidates"]:
        metadata = row["validation_metadata"]
        assert "score-source" in row["score_source_command_hint"]
        assert metadata["seed_source_retained"] == str(seed_path)
        assert metadata["seed_pcdump_path"] == "build/stack-clean-seed.pcdump.txt"


def test_draw_stack_clean_recovery_non_materializable_seed_terminalizes_per_goal(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    seed_path = Path(candidate["candidate_path"])
    seed_path.write_text(_draw_source(), encoding="utf-8")
    score = _draw_stack_clean_no_anchor_score(
        candidate,
        source_retained=str(seed_path),
    )
    handoff = classify_source_family_scores([candidate], [score], context)
    replay_context = normalize_meta_ceiling_context(
        [handoff],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    generated = generate_source_family_candidates(
        _draw_source(),
        replay_context,
        max_per_dimension=8,
        include_source=True,
    )
    payload = build_generated_source_family_payload(generated, replay_context)

    assert generated == []
    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    terminal_blockers = [
        row for row in payload["terminal_blockers"] if row.get("probe_id")
    ]
    assert [row["probe_id"] for row in terminal_blockers] == [
        "row-delta-anchor-local",
        "digit-fsubs-anchor-temp",
        "col-product-anchor-owner-transfer",
        "frame-clean-owner-prune",
    ]
    assert {row["reason"] for row in terminal_blockers} == {
        "draw-post-product-translate-stack-clean-no-anchor-recovery/source-span-not-materializable"
    }
    evidence = payload["source_model_proof"]["stack_clean_no_anchor_evidence"]
    assert evidence["source_retained"] == str(seed_path)
    assert evidence["pcdump_path"] == "build/stack-clean-seed.pcdump.txt"
    assert evidence["target_score"] == score["target_score"]
    assert evidence["expression_score"] == score["expression_score"]
    assert evidence["source_hunks"] == candidate["source_hunks"]


def test_draw_stack_clean_recovery_scored_probes_terminalize_with_retained_evidence(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    seed_source = _draw_stack_clean_seed_source()
    seed_path = Path(candidate["candidate_path"])
    seed_path.write_text(seed_source, encoding="utf-8")
    score = _draw_stack_clean_no_anchor_score(
        candidate,
        source_retained=str(seed_path),
    )
    handoff = classify_source_family_scores([candidate], [score], context)
    replay_context = normalize_meta_ceiling_context(
        [handoff],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    generated = generate_source_family_candidates(
        seed_source,
        replay_context,
        max_per_dimension=8,
        include_source=True,
    )
    written = write_source_family_candidates(
        generated,
        tmp_path / "scored-probes",
    )
    scores = _draw_stack_clean_failed_recovery_scores(written)

    payload = classify_source_family_scores(written, scores, replay_context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    )
    assert payload["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert payload["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert len(proof["candidate_scores"]) == 4
    assert len(proof["retained_scored_probes"]) == 4
    assert len(proof["source_hunks_by_candidate"]) == 4
    assert proof["stack_clean_no_anchor_evidence"]["source_retained"] == str(seed_path)
    assert (
        synthesis_payload["stack_clean_no_anchor_evidence"]
        == proof["stack_clean_no_anchor_evidence"]
    )
    assert all(
        row["seed_source_retained"] == str(seed_path)
        for row in proof["candidate_scores"]
    )
    assert DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION in {
        row["dimension_id"] for row in synthesis_payload["exhausted_dimensions"]
    }


def test_source_family_continuation_preserves_stack_clean_final_no_modeled_family():
    score = {
        "candidate_id": "draw-stack-clean-final-row",
        "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "source_retained": "build/stack-clean-final.c",
        "pcdump_path": "build/stack-clean-final.pcdump.txt",
        "source_hunks": [{"hunk_id": "stack-clean-final"}],
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26, "matched": False},
                "37": {"expected": 26, "actual": 28, "matched": False},
                "46": {"expected": 26, "actual": 2, "matched": False},
            },
        },
        "expression_score": {"matched": 0, "targeted": 3},
        "structural_guard": {"accepted": False, "frame_delta": 8},
        "frame_delta": 8,
    }
    evidence = {
        "seed_candidate_id": score["candidate_id"],
        "source_retained": score["source_retained"],
        "pcdump_path": score["pcdump_path"],
        "source_hunks": score["source_hunks"],
        "stack_frame_facts": {"frame_delta": 8},
    }
    exhausted = [
        {
            "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        }
    ]
    classified = {
        "function": DRAW_FUNCTION,
        "source_function": DRAW_SOURCE_FUNCTION,
        "status": "terminal",
        "kind": "post-meta-ceiling-fpr-source-family-synthesis-proof",
        "score_rows": [score],
        "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
        "next_unsupported_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "next_unsupported_source_family": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        ),
        "exhausted_dimensions": exhausted,
        "terminal_blockers": [
            {"reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER}
        ],
        "source_model_proof": {
            "candidate_scores": [score],
            "retained_scored_probes": [score],
            "attempted_equivalence_classes": [
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ],
            "exhausted_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "exhausted_dimensions": exhausted,
            "next_unsupported_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "next_unsupported_source_family": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
            ),
            "terminal_blockers": [
                {"reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER}
            ],
            "stack_clean_no_anchor_evidence": evidence,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "attempted_equivalence_classes": [
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
                ],
                "exhausted_dimensions": exhausted,
                "next_unsupported_source_dimension": (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
                ),
                "next_unsupported_source_family": (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
                ),
                "next_unsupported_source_model": (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
                ),
                "terminal_blockers": [
                    {"reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER}
                ],
                "stack_clean_no_anchor_evidence": evidence,
            },
        },
    }

    payload = build_source_family_continuation_payload(classified, [])

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    )
    assert payload["exhausted_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert payload["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    dimensions = {row["dimension_id"] for row in payload["exhausted_dimensions"]}
    assert DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION in dimensions
    assert DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER in (
        payload["terminal_blockers"]
    )
    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_MODEL
    )
    assert synthesis_payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert synthesis_payload["next_unsupported_source_dimension"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    )
    assert synthesis_payload["stack_clean_no_anchor_evidence"] == evidence


def test_draw_post_stack_clean_final_handoff_generates_next_shape_probes(
    tmp_path: Path,
) -> None:
    final_context, seed_source, seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )

    generated = generate_source_family_candidates(
        seed_source,
        final_context,
        max_per_dimension=8,
        include_source=True,
    )

    assert 0 < len(generated) <= 8
    assert {row["dimension_id"] for row in generated} == {
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith("draw-post-stack-clean-no-anchor-shape-")
        for row in generated
    )
    assert not any(
        row["candidate_id"].startswith(
            "draw-post-product-translate-stack-clean-no-anchor-"
        )
        for row in generated
    )
    for row in generated:
        metadata = row["validation_metadata"]
        assert metadata["stack_clean_no_anchor_evidence"]
        assert metadata["post_stack_clean_seed_candidate_id"]
        assert metadata["seed_source_retained"]
        assert metadata["stack_clean_no_anchor_evidence"]["source_retained"] == (
            str(seed_path)
        )
        assert row["source_hunks"]


def test_draw_stack_clean_final_continue_after_final_generates_post_stack_shape_only(
    tmp_path: Path,
) -> None:
    final_context, seed_source, seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )

    generated = generate_source_family_candidates(
        seed_source,
        final_context,
        continue_after_final_source_family=True,
        max_per_dimension=8,
        include_source=True,
    )

    assert generated
    assert {row["dimension_id"] for row in generated} == {
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith("draw-post-stack-clean-no-anchor-shape-")
        for row in generated
    )
    assert not any(
        row["candidate_id"].startswith(
            "draw-post-product-translate-stack-clean-no-anchor-"
        )
        for row in generated
    )
    for row in generated:
        metadata = row["validation_metadata"]
        assert metadata["post_stack_clean_no_anchor_source_shape"] is True
        assert metadata["stack_clean_no_anchor_evidence"]["source_retained"] == (
            str(seed_path)
        )


def test_draw_stack_clean_final_stale_continuation_bookkeeping_not_source_shape_terminal(
    tmp_path: Path,
) -> None:
    final_context, seed_source, _seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )
    stale_ceiling = {
        **final_context.current_ceiling,
        "continuation_attempts": [
            {
                "status": "continuation-exhausted",
                "next_unsupported_source_dimension": (
                    DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
                ),
                "candidate_ids": [],
            }
        ],
    }
    replay_context = replace(
        final_context,
        current_ceiling=stale_ceiling,
        next_unsupported_source_dimension=(
            DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
        ),
    )

    generated = generate_source_family_candidates(
        seed_source,
        replay_context,
        continue_after_final_source_family=True,
        max_per_dimension=8,
        include_source=True,
    )

    assert generated
    assert {row["dimension_id"] for row in generated} == {
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith("draw-post-stack-clean-no-anchor-shape-")
        for row in generated
    )
    assert not any(
        row["candidate_id"].startswith(
            "draw-post-product-translate-stack-clean-no-anchor-"
        )
        for row in generated
    )


def test_draw_stack_clean_final_without_evidence_terminalizes_no_replay(
    tmp_path: Path,
) -> None:
    exhausted = [
        {
            "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        }
    ]
    terminal = {
        "function": DRAW_FUNCTION,
        "source_function": DRAW_SOURCE_FUNCTION,
        "status": "terminal",
        "kind": "post-meta-ceiling-fpr-source-family-synthesis-proof",
        "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
        "next_unsupported_source_family": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        ),
        "exhausted_source_dimension": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "exhausted_dimensions": exhausted,
        "source_model_proof": {
            "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
            "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
            "exhausted_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "exhausted_dimensions": exhausted,
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "exhausted_dimensions": exhausted,
                "next_unsupported_source_family": (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
                ),
                "next_unsupported_source_model": (
                    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
                ),
            },
        },
    }
    context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    generated = generate_source_family_candidates(
        _draw_source(),
        context,
        continue_after_final_source_family=True,
        max_per_dimension=8,
        include_source=True,
    )
    payload = build_generated_source_family_payload(
        generated,
        context,
        continue_after_final_source_family=True,
    )

    assert generated == []
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    blockers = payload["generation_blockers"]
    blocker_reasons = {row["reason"] for row in blockers}
    blocker_terminals = {row["terminal_blocker"] for row in blockers}
    assert DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_PATTERN_BLOCKER in (
        blocker_reasons
    )
    assert DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_BLOCKER in (
        blocker_terminals
    )
    candidate_ids = []
    for source in (
        payload,
        payload["terminal_summary"],
        payload["post_ceiling_source_family_discovery"],
        payload["source_model_proof"],
        payload["source_model_proof"]["source_family_synthesis"],
    ):
        for key in (
            "generated_candidate_ids",
            "scored_candidate_ids",
            "all_candidate_ids",
            "available_candidate_ids",
        ):
            candidate_ids.extend(source.get(key) or [])
    assert not any(
        str(candidate_id).startswith(
            "draw-post-product-translate-stack-clean-no-anchor-"
        )
        for candidate_id in candidate_ids
    )


def test_draw_post_stack_clean_late_row_delta_fallback_keeps_existing_owner() -> None:
    function_text = (
        "    row_offset = y_offset * (f32) row;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "        if (row < 10) {\n"
    )

    patched = synthesis._patch_draw_post_stack_clean_row_delta_callsite_late(
        function_text
    )

    assert patched is not None
    assert "y_offset_owner" not in patched
    assert "row_offset = y_offset * (f32) row;" in patched


def test_draw_post_stack_clean_final_does_not_reterminalize_product_translate(
    tmp_path: Path,
) -> None:
    final_context, _seed_source, _seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )

    payload = build_generated_source_family_payload([], final_context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert payload["terminal_reason"] != (
        "draw-post-all-known-loop-product-translate-expression-graph-exhausted/no-floor-improvement"
    )


def test_draw_post_stack_clean_scored_rows_actionable_on_anchor_or_frame_improvement(
    tmp_path: Path,
) -> None:
    final_context, seed_source, _seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            final_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-clean-actionable",
    )
    anchor_score = _draw_stack_clean_no_anchor_score(
        candidates[0],
        accepted=True,
        expected_frame=168,
        current_frame=176,
        frame_delta=8,
    )
    anchor_score["target_score"]["virtuals"]["32"]["actual"] = 28
    anchor_score["target_score"]["matched"] = 1
    anchor_score["target_score"]["virtual_distance"] = 2
    anchor_score["expression_score"]["virtuals"]["37"]["actual"] = 26
    anchor_score["expression_score"]["matched"] = 1
    anchor_score["expression_score"]["virtual_distance"] = 2
    frame_score = _draw_stack_clean_no_anchor_score(
        candidates[1],
        accepted=True,
        current_frame=168,
        frame_delta=0,
    )
    rejected_frame = _draw_stack_clean_no_anchor_score(
        candidates[2],
        accepted=False,
        current_frame=168,
        frame_delta=0,
    )

    payload = classify_source_family_scores(
        candidates[:3],
        [anchor_score, frame_score, rejected_frame],
        final_context,
    )

    assert payload["status"] == "actionable"
    ranked_ids = [row["candidate_id"] for row in payload["ranked_candidates"]]
    assert candidates[0]["candidate_id"] in ranked_ids
    assert candidates[1]["candidate_id"] in ranked_ids
    assert candidates[2]["candidate_id"] not in ranked_ids


def test_draw_post_stack_clean_scored_rows_terminalize_with_retained_evidence(
    tmp_path: Path,
) -> None:
    final_context, seed_source, _seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            final_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-clean-terminal",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in candidates
    ]

    payload = classify_source_family_scores(candidates, scores, final_context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    proof = payload["source_model_proof"]
    assert proof["post_stack_clean_no_anchor_evidence"]
    assert proof["stack_clean_no_anchor_evidence"]
    assert len(proof["retained_scored_probes"]) == len(candidates)
    assert all(row["source_hunks"] for row in proof["source_hunks_by_candidate"])


def test_source_family_continuation_preserves_post_stack_clean_final_family(
    tmp_path: Path,
) -> None:
    final_context, seed_source, _seed_path = _draw_stack_clean_final_context_and_seed(
        tmp_path
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            final_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-clean-continuation",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in candidates
    ]
    terminal = classify_source_family_scores(candidates, scores, final_context)

    payload = build_source_family_continuation_payload(terminal, [])

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_MODEL
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )


def test_draw_post_stack_source_shape_final_handoff_generates_loop_callsite_probes(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, seed_path, source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )

    generated = generate_source_family_candidates(
        seed_source,
        post_stack_context,
        max_per_dimension=8,
        include_source=True,
    )

    assert generated
    assert {row["dimension_id"] for row in generated} == {
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith(
            "draw-post-stack-clean-no-anchor-loop-callsite-"
        )
        for row in generated
    )
    payload = build_generated_source_family_payload(generated, post_stack_context)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] == len(generated)
    assert payload["dimensions"] == [
        {
            "dimension_id": DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
            "generated_candidate_ids": [row["candidate_id"] for row in generated],
            "scored_candidate_ids": [],
            "candidate_count": len(generated),
            "scored_count": 0,
        }
    ]
    assert "terminal_reason" not in payload
    assert not any(
        row["candidate_id"].startswith("draw-post-stack-clean-no-anchor-shape-")
        for row in generated
    )
    for row in generated:
        metadata = row["validation_metadata"]
        assert metadata["post_stack_loop_callsite_source_context"] is True
        assert metadata["stack_clean_no_anchor_evidence"]
        assert metadata["post_stack_clean_no_anchor_evidence"]
        assert metadata["seed_source_retained"] in {
            candidate["source_retained"] for candidate in source_shape_candidates
        }
        assert metadata["seed_source_retained"] != str(seed_path)
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert row["source_hunks"]


def test_draw_post_stack_loop_callsite_scored_rows_terminalize_with_next_family(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-loop-callsite-terminal",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in candidates
    ]

    payload = classify_source_family_scores(candidates, scores, post_stack_context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )
    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert proof["post_stack_clean_no_anchor_evidence"]
    assert synthesis_payload["post_stack_clean_no_anchor_evidence"]
    assert len(proof["retained_scored_probes"]) == len(candidates)
    assert all(row["source_hunks"] for row in proof["source_hunks_by_candidate"])
    assert DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in synthesis_payload["exhausted_dimensions"]
    }


def test_source_family_continuation_preserves_loop_callsite_final_family(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-loop-callsite-continuation",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in candidates
    ]
    terminal = classify_source_family_scores(candidates, scores, post_stack_context)

    payload = build_source_family_continuation_payload(terminal, [])

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    assert "expression-anchor source ownership" in (
        payload["next_unsupported_source_model"]
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert payload["next_unsupported_source_model"] != DRAW_COUPLED_UNSUPPORTED_MODEL
    assert DRAW_COUPLED_UNSUPPORTED_CLASS not in json.dumps(payload)
    assert DRAW_COUPLED_UNSUPPORTED_MODEL not in json.dumps(payload)
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert proof_synthesis["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )


def test_draw_post_stack_loop_callsite_final_generates_expression_anchor_owner_probes(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-loop-callsite-final",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in candidates
    ]
    terminal = classify_source_family_scores(candidates, scores, post_stack_context)
    terminal_context = normalize_meta_ceiling_context(
        [terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    repeated = generate_source_family_candidates(
        seed_source,
        terminal_context,
        max_per_dimension=8,
        include_source=True,
    )
    payload = build_generated_source_family_payload(repeated, terminal_context)

    assert repeated
    assert payload["status"] == "generated"
    assert {row["dimension_id"] for row in repeated} == {
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    }
    assert {row["dimension_id"] for row in payload["dimensions"]} == {
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    }
    assert {
        "draw-post-stack-loop-callsite-expression-anchor-owner-row-offset-owner-split",
        "draw-post-stack-loop-callsite-expression-anchor-owner-digit-base-owner-split",
    } <= {row["candidate_id"] for row in repeated}
    assert DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION not in {
        row["dimension_id"] for row in repeated
    }
    assert DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY not in json.dumps(
        payload
    )
    for row in repeated:
        metadata = row["validation_metadata"]
        assert metadata[
            "post_stack_loop_callsite_expression_anchor_source_ownership"
        ] is True
        assert metadata["seed_source_retained"]
        assert metadata["seed_pcdump_path"]
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_structural_guard"] is True
        assert "--expression-baseline" in metadata["score_source_command_hint"]
        assert row["source_hunks"]
        assert row["source_components"]


def test_draw_expression_anchor_owner_scores_terminalize_with_final_family(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    loop_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-loop-callsite-owner-seed",
    )
    loop_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in loop_candidates
    ]
    loop_terminal = classify_source_family_scores(
        loop_candidates,
        loop_scores,
        post_stack_context,
    )
    owner_context = normalize_meta_ceiling_context(
        [loop_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    owner_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            owner_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "expression-anchor-owner-probes",
    )
    owner_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=8,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in owner_candidates
    ]

    payload = classify_source_family_scores(
        owner_candidates,
        owner_scores,
        owner_context,
    )

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
    )
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    assert DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY in {
        row["dimension_id"] for row in synthesis_payload["exhausted_dimensions"]
    }
    assert all(row["source_hunks"] for row in synthesis_payload["source_hunks_by_candidate"])


def test_draw_expression_anchor_owner_final_generates_post_row_offset_lifetime_probes(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    loop_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-lifetime-loop-seed",
    )
    loop_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in loop_candidates
    ]
    loop_terminal = classify_source_family_scores(
        loop_candidates,
        loop_scores,
        post_stack_context,
    )
    owner_context = normalize_meta_ceiling_context(
        [loop_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    owner_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            owner_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-lifetime-owner-seed",
    )
    owner_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=8,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in owner_candidates
    ]
    owner_terminal = classify_source_family_scores(
        owner_candidates,
        owner_scores,
        owner_context,
    )
    terminal_context = normalize_meta_ceiling_context(
        [owner_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    repeated = generate_source_family_candidates(
        seed_source,
        terminal_context,
        max_per_dimension=8,
        include_source=True,
    )
    payload = build_generated_source_family_payload(repeated, terminal_context)

    assert repeated
    assert payload["status"] == "generated"
    assert {row["dimension_id"] for row in repeated} == {
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    }
    assert all(row["source_hunks"] for row in repeated)
    assert any("row_offset_adj" in json.dumps(row) for row in repeated)
    assert any("digit" in json.dumps(row) for row in repeated)
    assert DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY not in {
        row["dimension_id"] for row in repeated
    }
    for row in repeated:
        metadata = row["validation_metadata"]
        assert metadata["post_row_offset_owner_expression_lifetime"] is True
        assert metadata["seed_source_retained"]
        assert metadata["seed_pcdump_path"]
        assert metadata["requires_target_score_validation"] is True
        assert metadata["requires_expression_score_validation"] is True
        assert metadata["requires_structural_guard"] is True


def test_draw_post_row_offset_owner_lifetime_scored_terminal_preserves_retained_evidence(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    loop_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-lifetime-scored-loop-seed",
    )
    loop_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in loop_candidates
    ]
    loop_terminal = classify_source_family_scores(
        loop_candidates,
        loop_scores,
        post_stack_context,
    )
    owner_context = normalize_meta_ceiling_context(
        [loop_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    owner_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            owner_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-lifetime-scored-owner-seed",
    )
    owner_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=8,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in owner_candidates
    ]
    owner_terminal = classify_source_family_scores(
        owner_candidates,
        owner_scores,
        owner_context,
    )
    terminal_context = normalize_meta_ceiling_context(
        [owner_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    lifetime_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            terminal_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-lifetime-scored-probes",
    )
    lifetime_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=8,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in lifetime_candidates
    ]

    payload = classify_source_family_scores(
        lifetime_candidates,
        lifetime_scores,
        terminal_context,
    )

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    evidence = proof_synthesis["post_row_offset_owner_expression_lifetime_evidence"]
    assert evidence["dimension_id"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    assert evidence["candidate_scores"]
    assert evidence["retained_scored_probes"]
    assert evidence["source_hunks_by_candidate"]
    assert all(
        row["dimension_id"] == DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        for row in evidence["candidate_scores"]
    )
    assert all(row["source_retained"] for row in evidence["retained_scored_probes"])
    assert all(row["pcdump_path"] for row in evidence["retained_scored_probes"])
    assert all(row["source_hunks"] for row in evidence["source_hunks_by_candidate"])
    assert evidence["ranked_post_row_offset_owner_expression_lifetime_seeds"]
    seed = evidence["ranked_post_row_offset_owner_expression_lifetime_seeds"][0]
    assert seed["source_retained"]
    assert seed["pcdump_path"]
    assert seed["source_hunks"]
    assert seed["stack_frame_facts"]["frame_delta"] == 8
    assert proof_synthesis["exhausted_source_dimension"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    assert any(
        row["dimension_id"] == DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        for row in proof_synthesis["exhausted_dimensions"]
    )


def test_draw_post_row_offset_owner_lifetime_zero_candidates_terminal_uses_lifetime_evidence(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    loop_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-zero-loop-seed",
    )
    loop_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in loop_candidates
    ]
    loop_terminal = classify_source_family_scores(
        loop_candidates,
        loop_scores,
        post_stack_context,
    )
    owner_context = normalize_meta_ceiling_context(
        [loop_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    owner_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            owner_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-zero-owner-seed",
    )
    owner_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=8,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in owner_candidates
    ]
    owner_terminal = classify_source_family_scores(
        owner_candidates,
        owner_scores,
        owner_context,
    )
    terminal_context = normalize_meta_ceiling_context(
        [owner_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    payload = build_generated_source_family_payload([], terminal_context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_FINAL_FAMILY
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert proof_synthesis["exhausted_source_dimension"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    assert any(
        row.get("reason") == DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_TERMINAL_BLOCKER
        for row in proof_synthesis["terminal_blockers"]
    )
    evidence = proof_synthesis["post_row_offset_owner_expression_lifetime_evidence"]
    assert evidence["dimension_id"] == (
        DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
    )
    assert evidence["ranked_post_row_offset_owner_expression_lifetime_seeds"]
    assert all(
        row["dimension_id"] == DRAW_POST_ROW_OFFSET_OWNER_EXPRESSION_LIFETIME_DIMENSION
        for row in proof_synthesis["source_hunks_by_candidate"]
    )
    assert evidence["source_retained"]
    assert evidence["pcdump_path"]
    assert evidence["source_hunks"]


def test_source_family_continuation_preserves_post_row_offset_owner_final_family(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    loop_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-continuation-loop-seed",
    )
    loop_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in loop_candidates
    ]
    loop_terminal = classify_source_family_scores(
        loop_candidates,
        loop_scores,
        post_stack_context,
    )
    owner_context = normalize_meta_ceiling_context(
        [loop_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    owner_candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            owner_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-row-offset-continuation-owner-seed",
    )
    owner_scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=8,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in owner_candidates
    ]
    owner_terminal = classify_source_family_scores(
        owner_candidates,
        owner_scores,
        owner_context,
    )

    payload = build_source_family_continuation_payload(owner_terminal, [])

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"]
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert proof_synthesis["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
    )


def test_draw_post_stack_loop_callsite_zero_candidates_terminalize_with_owner_handoff(
    tmp_path: Path,
) -> None:
    post_stack_context, _seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )

    payload = build_generated_source_family_payload([], post_stack_context)

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert synthesis_payload["exhausted_source_dimension"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )
    assert any(
        row.get("reason") == (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_PATTERN_BLOCKER
        )
        for row in synthesis_payload["next_unsupported_source_spans"]
    )


def test_draw_post_stack_loop_callsite_normalization_ignores_stale_next_dimension(
    tmp_path: Path,
) -> None:
    post_stack_context, seed_source, _seed_path, _source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            seed_source,
            post_stack_context,
            max_per_dimension=8,
            include_source=True,
        ),
        tmp_path / "post-stack-loop-callsite-mixed-final",
    )
    scores = [
        _draw_stack_clean_no_anchor_score(
            candidate,
            accepted=True,
            current_frame=184,
            frame_delta=16,
            source_retained=candidate["source_retained"],
            pcdump_path=f"build/{candidate['variant_id']}.pcdump.txt",
        )
        for candidate in candidates
    ]
    loop_callsite_terminal = classify_source_family_scores(
        candidates,
        scores,
        post_stack_context,
    )

    terminal_context = normalize_meta_ceiling_context(
        [post_stack_context.current_ceiling, loop_callsite_terminal],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )
    payload = build_generated_source_family_payload(
        [],
        terminal_context,
        continue_after_final_source_family=True,
    )

    assert terminal_context.next_unsupported_source_family == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert terminal_context.next_unsupported_source_model == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    assert terminal_context.next_unsupported_source_dimension is None
    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_POST_STACK_CLEAN_NO_ANCHOR_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_cli_source_model_synthesis_writes_draw_post_stack_loop_callsite_probes(
    tmp_path: Path,
) -> None:
    post_stack_context, _seed_source, _seed_path, source_shape_candidates = (
        _draw_post_stack_source_shape_terminal_context_and_seed(tmp_path)
    )
    aggregate_path = tmp_path / "post-stack-terminal.json"
    aggregate_path.write_text(
        json.dumps(post_stack_context.current_ceiling),
        encoding="utf-8",
    )
    output = tmp_path / "loop-callsite-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(aggregate_path),
            "--write-probes",
            str(output),
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] == 5
    assert {row["dimension_id"] for row in payload["candidates"]} == {
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith(
            "draw-post-stack-clean-no-anchor-loop-callsite-"
        )
        for row in payload["candidates"]
    )
    assert not any(
        path.name.startswith("draw-post-stack-clean-no-anchor-shape-")
        for path in output.glob("*.c")
    )
    retained_sources = {row["source_retained"] for row in source_shape_candidates}
    for row in payload["candidates"]:
        metadata = row["validation_metadata"]
        assert metadata["seed_source_retained"] in retained_sources


def test_draw_stack_clean_next_dimension_replay_keeps_post_helper_handoff(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    score = {
        **candidate,
        **_draw_stack_clean_no_anchor_score(candidate),
    }
    handoff = classify_source_family_scores([candidate], [score], context)
    post_helper_dimension = {
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "family_id": "post-source-context-fpr-ceiling-next-dimension",
        "function": DRAW_FUNCTION,
        "status": "unsupported-source-family",
        "trigger_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "trigger_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
        "exhausted_source_dimension": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "exhausted_dimensions": [DRAW_POST_SOURCE_CONTEXT_DIMENSION],
        "next_unsupported_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
        "source_spans": list(context.source_spans),
        "retained_evidence": [score],
        "stack_clean_no_anchor_evidence": handoff["source_model_proof"][
            "stack_clean_no_anchor_evidence"
        ],
    }
    replay_context = normalize_meta_ceiling_context(
        [post_helper_dimension],
        function=DRAW_FUNCTION,
        repo_root=tmp_path,
    )

    candidates = generate_source_family_candidates(
        _draw_source(),
        replay_context,
        max_per_dimension=8,
        include_source=True,
    )
    payload = build_generated_source_family_payload(candidates, replay_context)

    assert candidates == []
    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    proof = payload["source_model_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert synthesis_payload["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert (
        synthesis_payload["stack_clean_no_anchor_evidence"]["seed_candidate_id"]
        == candidate["candidate_id"]
    )
    assert DRAW_POST_SOURCE_CONTEXT_DIMENSION not in {
        row["dimension_id"] for row in synthesis_payload["blocked_dimensions"]
    }


def test_draw_product_translate_stack_clean_no_anchor_terminalizes_inactive_stage(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    context = replace(
        context,
        next_unsupported_source_dimension=None,
        next_unsupported_source_family=DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY,
        current_ceiling={
            **context.current_ceiling,
            "next_unsupported_source_family": (
                DRAW_PRODUCT_TRANSLATE_EXPRESSION_GRAPH_FINAL_FAMILY
            ),
        },
    )
    candidate = _draw_stack_clean_no_anchor_candidate(tmp_path)
    score = _draw_stack_clean_no_anchor_score(candidate)

    payload = classify_source_family_scores([candidate], [score], context)

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_dimension"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert (
        payload["source_model_proof"]["stack_clean_no_anchor_evidence"][
            "seed_candidate_id"
        ]
        == candidate["candidate_id"]
    )


def test_draw_stack_clean_no_anchor_evidence_ranking_prefers_opcode_clean_stack_row(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    stack_clean = _draw_stack_clean_no_anchor_candidate(tmp_path)
    other_candidates = [
        _draw_stack_clean_no_anchor_candidate(
            tmp_path,
            "draw-post-all-known-product-translate-graph-product-owners",
        ),
        _draw_stack_clean_no_anchor_candidate(
            tmp_path,
            "draw-post-all-known-product-translate-graph-row-before-col",
        ),
        _draw_stack_clean_no_anchor_candidate(
            tmp_path,
            "draw-post-all-known-product-translate-graph-common-translate-x",
        ),
    ]
    candidates = [*other_candidates, stack_clean]
    scores = [
        _draw_stack_clean_no_anchor_score(
            other_candidates[0],
            normalized_diff_lines=25,
            opcode_similarity=0.97,
        ),
        _draw_stack_clean_no_anchor_score(
            other_candidates[1],
            normalized_diff_lines=78,
            opcode_similarity=0.95,
        ),
        _draw_stack_clean_no_anchor_score(
            other_candidates[2],
            normalized_diff_lines=81,
            opcode_similarity=0.94,
        ),
        _draw_stack_clean_no_anchor_score(stack_clean),
    ]

    payload = classify_source_family_scores(candidates, scores, context)

    evidence = payload["source_model_proof"]["stack_clean_no_anchor_evidence"]
    assert evidence["seed_candidate_id"] == stack_clean["candidate_id"]
    assert (
        evidence["ranked_seed_candidates"][0]["candidate_id"]
        == (stack_clean["candidate_id"])
    )


def test_draw_stack_clean_no_anchor_recovery_false_positives_do_not_publish_evidence(
    tmp_path: Path,
) -> None:
    context = _draw_product_translate_expression_graph_context(tmp_path)
    cases = [
        {"classification": "control-flow"},
        {"opcode_similarity": 0.998},
        {"pcdump_path": None},
        {"accepted": True},
    ]
    for index, overrides in enumerate(cases):
        candidate = _draw_stack_clean_no_anchor_candidate(
            tmp_path,
            f"draw-post-all-known-product-translate-graph-false-positive-{index}",
        )
        score = _draw_stack_clean_no_anchor_score(candidate, **overrides)
        payload = classify_source_family_scores([candidate], [score], context)
        serialized = json.dumps(payload, sort_keys=True, default=str)
        assert "stack_clean_no_anchor_evidence" not in serialized


def test_draw_source_context_offline_score_above_floor_is_actionable(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)
    generated = generate_source_family_candidates(
        _draw_source(),
        context,
        include_source=True,
    )
    candidates = write_source_family_candidates(
        generated,
        tmp_path / "probes",
        include_source=False,
    )
    scores = [
        {
            **_draw_score(
                row,
                actual32=28 if index == 0 else 26,
                actual37=26 if index == 0 else 28,
                expression_actual32=28 if index == 0 else 26,
                expression_actual37=26 if index == 0 else 28,
            ),
            "pcdump_path": str(tmp_path / f"{row['candidate_id']}.pcdump.txt"),
        }
        for index, row in enumerate(candidates)
    ]

    classified = classify_source_family_scores(candidates, scores, context)

    assert classified["status"] == "actionable"
    best = classified["best_candidate"]
    assert best["dimension_id"] == DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION
    assert best["source_retained"]
    assert best["pcdump_path"]
    assert best["target_score"]
    assert best["expression_score"]
    assert best["source_hunks"]
    assert best["source_components"]


def test_draw_source_context_offline_no_floor_scores_emit_1035_terminal(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)
    generated = generate_source_family_candidates(
        _draw_source(),
        context,
        include_source=True,
    )
    candidates = write_source_family_candidates(
        generated,
        tmp_path / "probes",
        include_source=False,
    )
    scores = [
        {
            **_draw_score(row),
            "pcdump_path": str(tmp_path / f"{row['candidate_id']}.pcdump.txt"),
        }
        for row in candidates
    ]

    classified = classify_source_family_scores(candidates, scores, context)

    assert classified["status"] == "terminal"
    assert classified["terminal_reason"] == (
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert classified["next_unsupported_source_family"] == (
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert classified["next_unsupported_source_model"] == (
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_MODEL
    )
    assert {
        DRAW_ALTERNATE_DIMENSION,
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
    } <= set(classified["attempted_equivalence_classes"])
    assert DRAW_POST_ALTERNATE_SOURCE_CONTEXT_NO_FLOOR_BLOCKER in {
        blocker["reason"] for blocker in classified["terminal_blockers"]
    }
    assert any(
        row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
        for row in classified["retained_scored_probes"]
    )
    source_context_rows = [
        row
        for row in classified["retained_scored_probes"]
        if row["dimension_id"] == DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION
    ]
    assert source_context_rows
    assert all(row["source_retained"] for row in source_context_rows)
    assert all(row["pcdump_path"] for row in source_context_rows)
    assert all(row["target_score"] for row in source_context_rows)
    assert all(row["expression_score"] for row in source_context_rows)
    assert all(row["source_hunks"] for row in source_context_rows)
    assert all(row["source_components"] for row in source_context_rows)


def test_draw_source_context_terminal_reaches_retained_allocator(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)
    generated = generate_source_family_candidates(
        _draw_source(),
        context,
        include_source=True,
    )
    candidates = write_source_family_candidates(
        generated,
        tmp_path / "probes",
        include_source=False,
    )
    scores = [
        {
            **_draw_score(row),
            "pcdump_path": str(tmp_path / f"{row['candidate_id']}.pcdump.txt"),
        }
        for row in candidates
    ]
    terminal = classify_source_family_scores(candidates, scores, context)
    artifact = tmp_path / "draw-source-context-terminal.json"
    artifact.write_text(json.dumps(terminal), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert proof["source_hunks_by_candidate"]
    assert proof["retained_scored_probes"]
    assert result["status"] == "practical-ceiling"
    assert any(
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION in step
        for step in result["next_steps"]
    )
    assert any(
        DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY in step
        for step in result["next_steps"]
    )


def test_draw_source_context_zero_candidates_report_pattern_blocker(
    tmp_path: Path,
) -> None:
    context = _draw_post_alternate_source_context(tmp_path)
    source = """\
void mnDiagram_80241E78(void)
{
}
"""

    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
    )
    payload = build_generated_source_family_payload(candidates, context)

    assert candidates == []
    assert payload["status"] == "generated"
    blocker = next(
        row
        for row in payload["generation_blockers"]
        if row["dimension_id"] == DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION
    )
    assert blocker["reason"] == DRAW_POST_ALTERNATE_SOURCE_CONTEXT_PATTERN_BLOCKER
    assert blocker["required_source_patterns"]
    assert "terminal_blocker" not in blocker


def test_draw_alternate_terminal_reaches_retained_allocator(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    terminal = classify_source_family_scores(
        candidates,
        [
            _draw_floor_score(
                row,
                pcdump_path=f"build/{row['candidate_id']}.pcdump.txt",
            )
            for row in candidates
        ],
        context,
    )
    artifact = tmp_path / "draw-alternate-terminal.json"
    artifact.write_text(json.dumps(terminal), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    function = triaged["functions"][0]
    assert function["meta_ceiling"]["status"] == "terminal-current-source-shape-ceiling"
    proof = function["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY
    assert result["status"] == "practical-ceiling"
    assert (
        result["retained_frontiers_meta_ceiling"]["terminal_proof"][
            "next_unsupported_source_model"
        ]
        == DRAW_ALTERNATE_TERMINAL_MODEL
    )
    assert (
        "No modeled retained-frontier source-actionable lanes remain."
        in result["next_steps"]
    )
    assert any(DRAW_ALTERNATE_TERMINAL_MODEL in step for step in result["next_steps"])


def test_draw_alternate_target_above_floor_is_actionable(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    scores = [
        _draw_floor_score(row, pcdump_path="floor.pcdump.txt") for row in candidates
    ]
    scores[2] = _draw_score(candidates[2], actual32=28, actual37=26)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == candidates[2]["candidate_id"]
    assert payload["best_candidate"]["target_matched"] == 2


def test_draw_alternate_expression_above_floor_is_actionable(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    scores = [
        _draw_floor_score(row, pcdump_path="floor.pcdump.txt") for row in candidates
    ]
    scores[3] = _draw_score(
        candidates[3],
        expression_actual32=28,
        expression_actual37=26,
    )

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == candidates[3]["candidate_id"]
    assert payload["best_candidate"]["expression_matched"] == 2
    assert payload["best_candidate"]["target_matched"] == 0


def test_draw_alternate_mixed_old_floor_rows_do_not_action(
    tmp_path: Path,
) -> None:
    context, candidates = _draw_alternate_written_candidates(tmp_path)
    legacy = next(
        row
        for row in generate_source_family_candidates(
            _draw_source(),
            _draw_context(),
            max_per_dimension=1,
            include_source=True,
        )
        if row["dimension_id"] == DRAW_COUPLED_LIFETIME_DIMENSION
    )
    alternate = candidates[0]

    payload = classify_source_family_scores(
        [legacy, alternate],
        [
            _draw_floor_score(legacy, pcdump_path="legacy-floor.pcdump.txt"),
            _draw_floor_score(alternate, pcdump_path="alternate-floor.pcdump.txt"),
        ],
        context,
    )

    assert payload["status"] == "terminal"
    assert payload["terminal_blockers"][0]["reason"] == (
        DRAW_ALTERNATE_TERMINAL_BLOCKER
    )
    assert payload["next_unsupported_source_family"] == DRAW_ALTERNATE_TERMINAL_FAMILY


def test_rejected_structural_guard_blocks_terminal_proof(tmp_path: Path) -> None:
    context = _sort_context_without_broad_natural_evidence()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "probes",
    )
    scores = [_score(row) for row in candidates]
    scores[0] = _score(candidates[0], accepted=False)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "score-rows-not-terminal-safe"
    assert payload["blockers"][0]["reason"] == "structural-guard-not-accepted"


def test_sort_natural_structural_rejections_terminalize_with_blockers(
    tmp_path: Path,
) -> None:
    context = _context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "natural-structural-probes",
    )
    scores = [_score(row, accepted=False) for row in candidates]

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "terminal"
    assert payload["blockers"][0]["reason"] == "structural-guard-not-accepted"
    assert NATURAL_SORT_DIMENSIONS <= {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    assert (
        "broader natural C sort rewrite" not in payload["next_unsupported_source_model"]
    )


def _sort_semantic_structural_terminal_payload(tmp_path: Path) -> dict:
    context = _sort_semantic_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "semantic-structural-probes",
    )
    semantic = [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]
    assert semantic

    return classify_source_family_scores(
        semantic,
        [_score(row, accepted=False) for row in semantic],
        context,
    )


def test_sort_semantic_structural_rejections_terminalize_with_semantic_model(
    tmp_path: Path,
) -> None:
    payload = _sort_semantic_structural_terminal_payload(tmp_path)

    assert payload["status"] == "terminal"
    assert payload["blockers"][0]["reason"] == "structural-guard-not-accepted"
    assert payload["next_unsupported_source_model"] == (
        SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL
    )
    assert (
        payload["source_model_proof"]["source_family_synthesis"][
            "next_unsupported_source_model"
        ]
        == SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL
    )
    assert SEMANTIC_SORT_DIMENSIONS <= {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    retained = payload["source_model_proof"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    assert retained
    assert all(row["target_score"] for row in retained)
    assert all(row["structural_guard_accepted"] is False for row in retained)
    assert all(row["source_components"] for row in retained)
    assert "semantic_recombine" in payload
    assert (
        payload["source_model_proof"]["source_family_synthesis"]["semantic_recombine"]
        == payload["semantic_recombine"]
    )


def test_sort_partial_semantic_structural_rejection_stays_blocked(
    tmp_path: Path,
) -> None:
    context = _sort_semantic_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "partial-semantic-probes",
    )
    semantic = [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]

    payload = classify_source_family_scores(
        semantic[:1],
        [_score(semantic[0], accepted=False)],
        context,
    )

    assert payload["status"] == "blocked"
    assert payload["reason"] == "score-rows-not-terminal-safe"
    assert payload["blockers"][0]["reason"] == "structural-guard-not-accepted"


def test_sort_semantic_terminal_proof_triage_consumable(tmp_path: Path) -> None:
    payload = _sort_semantic_structural_terminal_payload(tmp_path)
    artifact = tmp_path / "sort-semantic-terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    frontier = next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert frontier["kind"] == "post-ceiling-gpr-case-c-source-model-synthesis-proof"
    assert frontier["attempted_targets"] == {"34": 27, "44": 25}
    synthesis_payload = frontier["source_model_proof"]["source_family_synthesis"]
    assert synthesis_payload["status"] == "synthesis-exhausted"
    assert synthesis_payload["next_unsupported_source_model"] == (
        SORT_SEMANTIC_ALGORITHM_EXHAUSTED_NEXT_MODEL
    )
    assert (
        "bounded IG34/IG44 semantic one-hit recombination"
        in (synthesis_payload["next_unsupported_source_model"])
    )
    assert payload["source_model_proof"]["source_family_synthesis"][
        "semantic_recombine"
    ]
    assert any(
        row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
        for row in synthesis_payload["retained_scored_probes"]
    )


def test_sort_semantic_one_hit_split_emits_recombine_proof(tmp_path: Path) -> None:
    context = _sort_semantic_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "semantic-recombine-probes",
    )
    semantic = [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]
    scores = [_score(row, accepted=False) for row in semantic]
    scores[0] = _score(semantic[0], actual34=27, actual44=22, accepted=False)
    scores[1] = _score(semantic[1], actual34=22, actual44=25, accepted=False)

    payload = classify_source_family_scores(semantic, scores, context)

    assert payload["status"] == "terminal"
    recombine = payload["semantic_recombine"]
    assert recombine["candidate_count"] > 0
    top = recombine["ranked_candidates"][0]
    assert len(top["parents"]) == 2
    assert top["target_score_estimate"]["matched"] == 2
    assert (
        payload["source_model_proof"]["source_family_synthesis"]["semantic_recombine"]
        == recombine
    )
    blocker_reasons = {
        row["reason"] for row in payload["terminal_blockers"] if isinstance(row, dict)
    }
    assert blocker_reasons & {
        "semantic-recombine-overlapping-components",
        "semantic-recombine-overlapping-source-hunks",
        "semantic-recombine-missing-source-hunks",
    }


def test_sort_semantic_recombine_materializes_source_candidate() -> None:
    source = """\
void fn(void)
{
    old34();
    keep();
    old44();
}
"""
    recombine = {
        "semantic_recombine": {
            "status": "actionable",
            "ranked_candidates": [
                {
                    "candidate_id": "post-meta-sort-semantic-recombine-test",
                    "dimension_id": SORT_SEMANTIC_RECOMBINE_DIMENSION,
                    "accepted": True,
                    "blockers": [],
                    "parents": ["ig34", "ig44"],
                    "source_hunks": [
                        {
                            "hunk_id": "ig34-hunk",
                            "base_start": 2,
                            "base_end": 3,
                            "candidate_start": 2,
                            "candidate_end": 3,
                            "removed": ["    old34();"],
                            "added": ["    new34();"],
                        },
                        {
                            "hunk_id": "ig44-hunk",
                            "base_start": 4,
                            "base_end": 5,
                            "candidate_start": 4,
                            "candidate_end": 5,
                            "removed": ["    old44();"],
                            "added": ["    new44();"],
                        },
                    ],
                    "source_components": [
                        {"component_id": "ig34-owner"},
                        {"component_id": "ig44-owner"},
                    ],
                    "target_score_estimate": {
                        "matched": 2,
                        "targeted": 2,
                        "estimated": True,
                    },
                }
            ],
        }
    }

    materialized = materialize_semantic_recombine_source_candidates(
        recombine,
        source,
        _context(),
        max_candidates=2,
        validation_options={
            "target": "target.json",
            "cflags_from": "src/melee/mn/mndiagram.c",
            "expression_source": "src/melee/mn/mndiagram.c",
            "checkdiff_guard": True,
        },
        include_source=True,
    )

    assert materialized["failures"] == []
    candidates = materialized["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["candidate_id"] == "post-meta-sort-semantic-recombine-test"
    assert candidate["dimension_id"] == SORT_SEMANTIC_RECOMBINE_DIMENSION
    assert "    new34();" in candidate["source_text"]
    assert "    new44();" in candidate["source_text"]
    assert "    old34();" not in candidate["source_text"]
    assert "    old44();" not in candidate["source_text"]
    assert candidate["source_hunks"] == recombine["semantic_recombine"][
        "ranked_candidates"
    ][0]["source_hunks"]
    metadata = candidate["validation_metadata"]
    assert metadata["requires_full_unit_source"] is True
    assert metadata["requires_structural_guard"] is True
    assert metadata["required_preserved_assignments"] == ["IG34->r27", "IG44->r25"]
    assert "--full-unit-source" in metadata["score_source_command_hint"]


def test_sort_semantic_recombine_materialization_scores_public_source_function() -> None:
    source = """\
void mnDiagram_SortNamesByKOs(void)
{
    old34();
    keep();
    old44();
}
"""
    recombine = {
        "semantic_recombine": {
            "status": "actionable",
            "ranked_candidates": [
                {
                    "candidate_id": "post-meta-sort-semantic-recombine-public",
                    "dimension_id": SORT_SEMANTIC_RECOMBINE_DIMENSION,
                    "accepted": True,
                    "blockers": [],
                    "source_hunks": [
                        {
                            "hunk_id": "ig34-hunk",
                            "base_start": 2,
                            "base_end": 3,
                            "candidate_start": 2,
                            "candidate_end": 3,
                            "removed": ["    old34();"],
                            "added": ["    new34();"],
                        }
                    ],
                }
            ],
        }
    }

    materialized = materialize_semantic_recombine_source_candidates(
        recombine,
        source,
        _context(),
        max_candidates=1,
        validation_options={
            "target": "target.json",
            "cflags_from": "src/melee/mn/mndiagram.c",
            "expression_source": "src/melee/mn/mndiagram.c",
            "checkdiff_guard": True,
        },
        include_source=True,
    )

    assert materialized["failures"] == []
    candidate = materialized["candidates"][0]
    metadata = candidate["validation_metadata"]
    assert candidate["source_function"] == SORT_FUNCTION
    assert metadata["source_function"] == SORT_FUNCTION
    assert metadata["score_function"] == SORT_FUNCTION
    assert f"--function {SORT_FUNCTION}" in metadata["score_source_command_hint"]
    assert SORT_SOURCE_FUNCTION not in metadata["score_source_command_hint"]
    assert "--full-unit-source" in metadata["score_source_command_hint"]


def test_sort_semantic_recombine_materialization_reports_hunk_mismatch() -> None:
    source = "void fn(void)\n{\n    old34();\n}\n"
    payload = {
        "semantic_recombine": {
            "status": "actionable",
            "ranked_candidates": [
                {
                    "candidate_id": "post-meta-sort-semantic-recombine-mismatch",
                    "dimension_id": SORT_SEMANTIC_RECOMBINE_DIMENSION,
                    "accepted": True,
                    "blockers": [],
                    "source_hunks": [
                        {
                            "hunk_id": "bad-hunk",
                            "base_start": 2,
                            "base_end": 3,
                            "candidate_start": 2,
                            "candidate_end": 3,
                            "removed": ["    stale34();"],
                            "added": ["    new34();"],
                        }
                    ],
                }
            ],
        }
    }

    materialized = materialize_semantic_recombine_source_candidates(
        payload,
        source,
        _context(),
        max_candidates=1,
        validation_options={},
        include_source=True,
    )

    assert materialized["candidates"] == []
    assert materialized["attempted_candidate_count"] == 1
    assert materialized["failures"][0]["candidate_id"] == (
        "post-meta-sort-semantic-recombine-mismatch"
    )
    assert materialized["failures"][0]["reason"] == "hunk-apply-failed"


def test_cli_source_model_synthesis_scores_materialized_semantic_recombine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = _sort_semantic_context()
    meta = tmp_path / "sort-semantic-meta.json"
    meta.write_text(
        json.dumps(
            {
                "function": SORT_FUNCTION,
                "status": "practical-ceiling",
                "source_shape_exhausted": True,
                "current_ceiling": context.current_ceiling,
            }
        ),
        encoding="utf-8",
    )
    source_text = """\
void mnDiagram_SortNamesByKOs(void)
{
    old34();
    keep();
    old44();
}
"""
    source = tmp_path / "sort.c"
    source.write_text(source_text, encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    output = tmp_path / "probes"
    score_calls: list[list[dict]] = []

    def semantic_candidate(
        candidate_id: str,
        dimension_id: str,
        *,
        old_start: int,
        old_line: str,
        new_line: str,
        component_id: str,
    ) -> dict:
        return {
            "candidate_id": candidate_id,
            "dimension_id": dimension_id,
            "equivalence_class": dimension_id,
            "variant_id": candidate_id,
            "source_text": source_text.replace(old_line, new_line),
            "source_hunks": [
                {
                    "hunk_id": candidate_id,
                    "base_start": old_start - 1,
                    "base_end": old_start,
                    "candidate_start": old_start - 1,
                    "candidate_end": old_start,
                    "old_start": old_start,
                    "old_end": old_start + 1,
                    "old_lines": [old_line],
                    "new_lines": [new_line],
                    "removed": [old_line],
                    "added": [new_line],
                }
            ],
            "source_components": [_sort_semantic_component(component_id)],
            "validation_metadata": {
                "candidate_id": candidate_id,
                "dimension_id": dimension_id,
                "function": SORT_FUNCTION,
                "source_function": SORT_FUNCTION,
                "score_function": SORT_FUNCTION,
                "final_force_phys": {"34": 27, "44": 25},
            },
        }

    def fake_generate_source_family_candidates(*_args, **_kwargs):
        rows = [
            semantic_candidate(
                "semantic-ig34-owner",
                "sort-semantic-loop-ownership",
                old_start=3,
                old_line="    old34();",
                new_line="    new34();",
                component_id="sort-loop-ownership",
            ),
            semantic_candidate(
                "semantic-ig44-selection",
                "sort-semantic-selected-name-extraction",
                old_start=5,
                old_line="    old44();",
                new_line="    new44();",
                component_id="sort-selected-name-extraction",
            ),
        ]
        remaining_dimensions = sorted(
            SEMANTIC_SORT_DIMENSIONS
            - {
                "sort-semantic-loop-ownership",
                "sort-semantic-selected-name-extraction",
            }
        )
        for index, dimension in enumerate(remaining_dimensions, start=1):
            rows.append(
                semantic_candidate(
                    f"semantic-nohit-{index}",
                    dimension,
                    old_start=4,
                    old_line="    keep();",
                    new_line=f"    keep(); /* {index} */",
                    component_id=f"semantic-nohit-{index}",
                )
            )
        return rows

    def fake_score_source_candidates(candidates, **_kwargs):
        def row_hunk_ranges(row: dict) -> set[tuple[int, int]]:
            return {
                (int(hunk["base_start"]), int(hunk["base_end"]))
                for hunk in row.get("source_hunks", [])
            }

        def ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
            return max(left[0], right[0]) < min(left[1], right[1])

        rows = [dict(row) for row in candidates]
        score_calls.append(rows)
        if len(score_calls) == 1:
            semantic_rows = [
                row for row in rows if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
            ]
            selected_pair = None
            for left_index, left in enumerate(semantic_rows):
                left_spans = row_hunk_ranges(left)
                left_components = {
                    item.get("component_id")
                    for item in left.get("source_components", [])
                    if isinstance(item, dict)
                }
                for right in semantic_rows[left_index + 1 :]:
                    right_spans = row_hunk_ranges(right)
                    right_components = {
                        item.get("component_id")
                        for item in right.get("source_components", [])
                        if isinstance(item, dict)
                    }
                    if (
                        not any(
                            ranges_overlap(left_span, right_span)
                            for left_span in left_spans
                            for right_span in right_spans
                        )
                    ) and left_components.isdisjoint(
                        right_components
                    ):
                        selected_pair = {
                            left["candidate_id"]: "34",
                            right["candidate_id"]: "44",
                        }
                        break
                if selected_pair is not None:
                    break
            assert selected_pair is not None
            scores = []
            for row in rows:
                if selected_pair.get(row["candidate_id"]) == "34":
                    scores.append(
                        _score(row, actual34=27, actual44=22, accepted=False)
                    )
                elif selected_pair.get(row["candidate_id"]) == "44":
                    scores.append(
                        _score(row, actual34=22, actual44=25, accepted=False)
                    )
                else:
                    scores.append(_score(row, accepted=False))
            return scores
        assert {row["dimension_id"] for row in rows} == {
            SORT_SEMANTIC_RECOMBINE_DIMENSION
        }
        for row in rows:
            metadata = row["validation_metadata"]
            assert row["source_function"] == SORT_FUNCTION
            assert metadata["source_function"] == SORT_FUNCTION
            assert metadata["score_function"] == SORT_FUNCTION
            assert f"--function {SORT_FUNCTION}" in row["score_command"]
            assert SORT_SOURCE_FUNCTION not in row["score_command"]
            assert metadata["requires_full_unit_source"] is True
        return [
            {
                **_score(row, actual34=27, actual44=25, accepted=True),
                "pcdump_path": str(
                    tmp_path / f"{row['candidate_id']}.pcdump.txt"
                ),
            }
            for row in rows
        ]

    monkeypatch.setattr(
        synthesis,
        "generate_source_family_candidates",
        fake_generate_source_family_candidates,
    )
    monkeypatch.setattr(
        synthesis,
        "score_source_candidates",
        fake_score_source_candidates,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(output),
            "--target",
            str(target),
            "--score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(score_calls) == 2
    assert score_calls[1]
    assert {row["dimension_id"] for row in score_calls[1]} == {
        SORT_SEMANTIC_RECOMBINE_DIMENSION
    }
    assert payload["context"]["source_function"] == SORT_FUNCTION
    assert all(Path(row["source_retained"]).is_file() for row in score_calls[1])
    assert payload["score_mode"] == "live"
    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "actionable"
    scored = semantic["ranked_candidates"][0]
    assert scored["source_retained"].endswith(".c")
    assert scored["pcdump_path"].endswith(".pcdump.txt")
    assert scored["source_hunks"]
    assert scored["target_score"]["matched"] == 2
    assert scored["target_score"].get("estimated") is not True
    assert scored["target_score_estimate"]["estimated"] is True
    assert scored["structural_guard"]["accepted"] is True
    assert scored["structural_guard"].get("estimated") is not True


def test_sort_semantic_nonoverlapping_continuation_needs_real_score() -> None:
    rows = [
        _sort_one_hit_row(
            "post-meta-sort-semantic-owner-dst-local-only",
            "sort-semantic-loop-ownership",
            hit_virtual="34",
            hunk_start=10,
            component_id="sort-loop-ownership",
            source_retained="ig34.c",
        ),
        _sort_one_hit_row(
            "post-meta-sort-semantic-selected-name-after-inner",
            "sort-semantic-selected-name-extraction",
            hit_virtual="44",
            hunk_start=20,
            component_id="sort-selected-name-extraction",
            source_retained="ig44.c",
        ),
    ]

    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(rows),
        [],
    )

    assert payload["status"] == "blocked"
    assert payload["terminal"] is False
    assert payload["accepted_candidates"] == []
    assert payload["continuation"] is None
    assert payload["continuation_artifacts"][0]["kind"] == (
        "sort-semantic-dual-target-recombine"
    )
    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "blocked"
    proposal = semantic["ranked_candidates"][0]
    assert proposal["dimension_id"] == SORT_SEMANTIC_RECOMBINE_DIMENSION
    assert proposal["accepted"] is False
    assert proposal["target_score"] is None
    assert proposal["target_score_estimate"]["matched"] == 2
    assert "no-scored-recombine-evidence" in proposal["blockers"]


def test_sort_raw_combine_scores_supersede_estimated_semantic_recombine_original_ids() -> (
    None
):
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_raw_combine_original_id_parent_rows()),
        [_sort_raw_search_combine_real_score_terminal()],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert payload["real_score_authority"] == "semantic-recombine-real-score"
    assert "unrecognized-continuation-artifact" not in payload["terminal_blockers"]
    assert {
        "real-score-protected-loss",
        "one-hit-recombine-protected-targets-not-jointly-preserved",
        "recombine-overlapping-source-hunks",
        "no-scored-recombine-evidence",
    } <= set(payload["terminal_blockers"])

    search_summary = next(
        row
        for row in payload["continuation_artifacts"]
        if row["kind"] == "search-combine"
    )
    assert search_summary["score_coverage"] == {
        "ok_combinations": 3,
        "skipped_combinations": 1,
        "evaluable_combinations": 3,
        "joint_preserving_combinations": 0,
    }

    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "terminal"
    accepted_estimates = [
        row
        for row in semantic["ranked_candidates"]
        if row.get("accepted") is True
        and isinstance(row.get("target_score"), dict)
        and row["target_score"].get("estimated") is True
    ]
    assert accepted_estimates == []
    assert any(
        row.get("real_score_superseded_by") for row in semantic["ranked_candidates"]
    )
    unscored = [
        row
        for row in semantic["ranked_candidates"]
        if "no-scored-recombine-evidence" in row.get("blockers", [])
    ]
    assert unscored
    assert all(row["accepted"] is False for row in unscored)
    assert (
        payload["source_model_proof"]["source_family_synthesis"]["semantic_recombine"]
        == semantic
    )


def test_sort_raw_combine_joint_hit_keeps_semantic_recombine_actionable_with_retained_source() -> (
    None
):
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_raw_search_combine_joint_hit()],
    )

    assert payload["status"] == "actionable"
    assert payload["terminal"] is False
    assert payload["continuation"]["route"] == "sort-semantic-dual-target-recombine"
    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "actionable"
    accepted = [
        row for row in semantic["ranked_candidates"] if row.get("accepted") is True
    ]
    assert len(accepted) == 1
    candidate = accepted[0]
    assert candidate["source_retained"] == "build/sort/combine-joint-hit.c"
    assert candidate["target_score"]["matched"] == 2
    assert candidate["target_score"].get("estimated") is not True
    assert candidate["target_score_estimate"]["estimated"] is True


def test_sort_continuation_real_score_supersedes_estimated_recombine() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_combine_real_score_protected_loss_terminal()],
    )

    assert payload["continuation"]["route"] != "sort-semantic-dual-target-recombine"
    assert not [
        row
        for row in payload["accepted_candidates"]
        if row.get("dimension_id") == SORT_SEMANTIC_RECOMBINE_DIMENSION
    ]
    semantic = payload["semantic_recombine"]
    superseded = semantic["ranked_candidates"][0]
    assert superseded["accepted"] is False
    assert superseded["structural_guard"]["accepted"] is False
    assert superseded["structural_guard"]["status"] == "real-score-protected-loss"
    assert superseded["target_score_estimate"]["matched"] == 2
    assert superseded["target_score"]["matched"] == 1
    assert "real-score-protected-loss" in superseded["blockers"]

    protected_summary = next(
        row
        for row in payload["continuation_artifacts"]
        if row["kind"] == "protected-structural-synthesis"
    )
    real_candidate = next(
        row
        for row in protected_summary["ranked_candidates"]
        if row["candidate_id"] == "combine-selected-name-owner-dst"
    )
    assert real_candidate["target_score"]["matched"] == 1
    assert real_candidate["target_score_total"] == 24
    assert real_candidate["pcdump_path"].endswith(".pcdump.txt")
    assert real_candidate["missing_protected_assignments"] == [{"ig": 34, "phys": 27}]
    assert real_candidate["satisfied_protected_assignments"] == [{"ig": 44, "phys": 25}]
    assert real_candidate["protected_assignments_satisfied"] is False
    assert all(isinstance(row, dict) for row in protected_summary["next_actions"])
    assert {
        "lower-drift-candidates-lost-protected-assignments",
        "recombine-overlapping-source-hunks",
        "protected-structural-synthesis-exhausted",
    } <= set(payload["terminal_blockers"])


def test_sort_continuation_alias_real_score_supersedes_estimated_recombine() -> None:
    parent_rows = _sort_real_score_parent_rows()
    parent_rows[0]["source_retained"] = (
        "build/source-model/scored/post-meta-source-family-sort-init-indexed-write-name-total-locals.c"
    )
    parent_rows[1]["source_retained"] = (
        "build/source-model/scored/post-meta-source-family-sort-call-return-copy-local-max-text-copy.c"
    )
    artifact = _sort_combine_real_score_protected_loss_terminal(
        include_repair_seed=False
    )
    artifact["candidates"] = [
        {
            "candidate_id": "init",
            "path": (
                "/tmp/worktree/build/source-model/scored/"
                "post-meta-source-family-sort-init-indexed-write-name-total-locals.c"
            ),
        },
        {
            "candidate_id": "maxtext",
            "path": (
                "/tmp/worktree/build/source-model/scored/"
                "post-meta-source-family-sort-call-return-copy-local-max-text-copy.c"
            ),
        },
    ]
    for row in artifact["combinations"]:
        row["candidate_id"] = "combine-init-maxtext"
        row["parents"] = ["init", "maxtext"]
    synthesis = artifact["protected_structural_synthesis"]
    for key in ("ranked_candidates", "lower_drift_lost_protected_candidates"):
        for row in synthesis[key]:
            row["candidate_id"] = "combine-init-maxtext"
            row["parents"] = ["init", "maxtext"]

    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(parent_rows),
        [artifact],
    )

    assert payload["status"] == "terminal"
    assert payload["continuation"] is None
    assert not [
        row
        for row in payload["accepted_candidates"]
        if row.get("dimension_id") == SORT_SEMANTIC_RECOMBINE_DIMENSION
    ]
    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "terminal"
    superseded = semantic["ranked_candidates"][0]
    assert superseded["accepted"] is False
    assert superseded["target_score_estimate"]["matched"] == 2
    assert superseded["target_score"]["matched"] == 1
    assert superseded["real_score_superseded_by"] == "combine-init-maxtext"
    assert "real-score-protected-loss" in superseded["blockers"]

    protected_summary = next(
        row
        for row in payload["continuation_artifacts"]
        if row["kind"] == "protected-structural-synthesis"
    )
    real_candidate = protected_summary["ranked_candidates"][0]
    assert real_candidate["resolved_parents"] == [
        "post-meta-sort-semantic-owner-dst-local-only",
        "post-meta-sort-semantic-selected-name-after-inner",
    ]
    assert real_candidate["target_score"]["matched"] == 1
    assert real_candidate["source_hunks"] == [
        _sort_semantic_hunk(10),
        _sort_semantic_hunk(30),
    ]


def test_sort_real_combine_short_parent_labels_supersede_estimated_recombine() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_short_label_real_score_parent_rows()),
        [
            _sort_select_order_context_artifact(),
            _sort_short_label_combine_real_score_terminal(),
        ],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert payload["real_score_authority"] == "semantic-recombine-real-score"
    assert "unrecognized-continuation-artifact" not in payload["terminal_blockers"]
    assert (
        "full Sort selection/swap source structure"
        in payload["next_unsupported_source_model"]
    )
    assert (
        payload["source_model_proof"]["source_family_synthesis"][
            "next_unsupported_source_model"
        ]
        == payload["next_unsupported_source_model"]
    )

    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "terminal"
    superseded = [
        row
        for row in semantic["ranked_candidates"]
        if row.get("real_score_superseded_by")
    ]
    assert len(superseded) == 3
    assert not [
        row
        for row in payload["accepted_candidates"]
        if row.get("dimension_id") == SORT_SEMANTIC_RECOMBINE_DIMENSION
    ]
    assert set(payload["suppressed_estimated_candidate_ids"]) == {
        row["candidate_id"] for row in superseded
    }
    assert all(row["accepted"] is False for row in superseded)
    assert all(row["target_score_estimate"]["matched"] == 2 for row in superseded)
    assert all(row["target_score"]["matched"] < 2 for row in superseded)
    assert all("real-score-protected-loss" in row["blockers"] for row in superseded)

    protected_summary = next(
        row
        for row in payload["continuation_artifacts"]
        if row["kind"] == "protected-structural-synthesis"
    )
    real_candidate = next(
        row
        for row in protected_summary["ranked_candidates"]
        if row["candidate_id"] == "combine-ig34-ig44_byte"
        and row["dimension_id"] != SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
    )
    assert real_candidate["resolved_parents"] == [
        "post-meta-source-family-sort-init-indexed-write-name-total-locals",
        "post-meta-source-family-sort-indexed-byte-cache-byte-cache",
    ]
    assert real_candidate["source_hunks"] == [
        _sort_semantic_hunk(10),
        _sort_semantic_hunk(50),
    ]
    assert {row["dimension_id"] for row in payload["blocked_dimensions"]} == {
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    }


def test_sort_raw_score_source_supersedes_estimated_semantic_recombine() -> None:
    classified = _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows())
    estimate = build_source_family_continuation_payload(classified, [])
    candidate_id = estimate["semantic_recombine"]["ranked_candidates"][0][
        "candidate_id"
    ]
    raw_score = _sort_raw_semantic_recombine_score(
        candidate_id,
        target_score=_sort_real_target_score(actual34=None, actual44=25),
        structural_guard={
            "accepted": False,
            "classification_primary": "inline-boundary-toolchain-artifact",
        },
    )

    payload = build_source_family_continuation_payload(classified, [raw_score])

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert payload["real_score_authority"] == "semantic-recombine-real-score"
    assert payload["suppressed_estimated_candidate_ids"] == [candidate_id]

    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "terminal"
    superseded = semantic["ranked_candidates"][0]
    assert superseded["accepted"] is False
    assert superseded["real_score_superseded_by"] == candidate_id
    assert superseded["target_score_estimate"]["matched"] == 2
    assert superseded["target_score"]["matched"] == 1
    assert superseded["structural_guard"]["status"] == "real-score-protected-loss"
    assert "real-score-protected-loss" in superseded["blockers"]

    score_summary = next(
        row
        for row in payload["continuation_artifacts"]
        if row["kind"] == "score-source"
    )
    score_candidate = score_summary["ranked_candidates"][0]
    assert score_candidate["candidate_id"] == candidate_id
    assert score_candidate["dimension_id"] == SORT_SEMANTIC_RECOMBINE_DIMENSION


def test_sort_raw_score_source_terminal_reaches_retained_allocator(
    tmp_path: Path,
) -> None:
    payload = _sort_raw_score_source_terminal_payload()
    artifact = tmp_path / "sort-semantic-real-score-terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    function_payload = triaged["functions"][0]
    assert function_payload["frontiers"] == []
    assert not any(
        isinstance(frontier.get("continuation"), dict)
        and frontier["continuation"].get("route")
        == "sort-semantic-dual-target-recombine"
        for frontier in function_payload["frontiers"]
    )
    assert function_payload["meta_ceiling"]["status"] == (
        "terminal-current-source-shape-ceiling"
    )

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"
    )
    assert not any(
        "retained-frontier source hunk" in step for step in result["next_steps"]
    )


def test_sort_raw_score_source_preserving_all_keeps_semantic_recombine_actionable() -> (
    None
):
    classified = _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows())
    estimate = build_source_family_continuation_payload(classified, [])
    candidate_id = estimate["semantic_recombine"]["ranked_candidates"][0][
        "candidate_id"
    ]
    raw_score = _sort_raw_semantic_recombine_score(
        candidate_id,
        target_score=_sort_real_target_score(actual34=27, actual44=25),
        structural_guard={"accepted": True},
        source_retained=f"build/sort/{candidate_id}.c",
    )

    payload = build_source_family_continuation_payload(classified, [raw_score])

    assert payload["status"] == "actionable"
    assert payload["continuation"]["route"] == "sort-semantic-dual-target-recombine"
    semantic = payload["semantic_recombine"]
    semantic_candidate = next(
        row
        for row in semantic["ranked_candidates"]
        if row["candidate_id"] == candidate_id
    )
    assert "real_score_superseded_by" not in semantic_candidate
    assert semantic_candidate["target_score"]["matched"] == 2
    assert "real-score-protected-loss" not in semantic_candidate["blockers"]


def test_retained_frontier_merge_preserves_real_score_protected_loss_fields(
    tmp_path: Path,
) -> None:
    frontier_id = "mnDiagram_SortNamesByKOs:semantic-recombine-real-score"
    actionable_artifact = tmp_path / "estimated-frontier.json"
    terminal_artifact = tmp_path / "terminal-frontier.json"
    base = {
        "function": SORT_FUNCTION,
        "frontier_id": frontier_id,
        "family_id": "post-ceiling-source-model-proof",
        "attempted_targets": {"34": 27, "44": 25},
        "protected_targets": {"34": 27, "44": 25},
        "final_force_phys": {"34": 27, "44": 25},
    }
    actionable_artifact.write_text(
        json.dumps(
            {
                **base,
                "status": "actionable",
                "terminal": False,
                "continuation": {
                    "route": "sort-semantic-dual-target-recombine",
                    "candidate_id": "post-meta-sort-semantic-recombine-estimated",
                    "source_hunks": [_sort_semantic_hunk(10)],
                },
            }
        ),
        encoding="utf-8",
    )
    terminal_artifact.write_text(
        json.dumps(
            {
                **base,
                "status": "terminal",
                "terminal": True,
                "terminal_reason": "current-source-shape-ceiling",
                "real_score_authority": "semantic-recombine-real-score",
                "terminal_blockers": ["real-score-protected-loss"],
                "protected_loss_negative_evidence": {
                    "reason": "real-score-protected-loss"
                },
                "source_model_proof": {
                    "source_family_synthesis": {
                        "terminal_blockers": ["real-score-protected-loss"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[actionable_artifact, terminal_artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    assert triaged["functions"][0]["frontiers"] == []
    terminal = next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row["frontier_id"] == frontier_id
    )
    assert terminal["real_score_authority"] == "semantic-recombine-real-score"
    assert terminal["terminal_blockers"] == ["real-score-protected-loss"]
    assert terminal["protected_loss_negative_evidence"] == {
        "reason": "real-score-protected-loss"
    }
    assert terminal["suppressed_by_terminal"] is True


def test_sort_select_order_artifact_is_context_not_unrecognized() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_select_order_context_artifact()],
    )

    select_summary = next(
        row
        for row in payload["continuation_artifacts"]
        if row["kind"] == "context-only-select-order"
    )
    assert select_summary["status"] == "context-only"
    assert select_summary["terminal_blockers"] == []
    assert "unrecognized-continuation-artifact" not in payload["terminal_blockers"]


def test_sort_generic_probe_artifact_is_not_select_order_actionable() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [
            {
                "function": SORT_FUNCTION,
                "status": "ok",
                "ranking": "generic-probe-ranking",
                "probes": [
                    {
                        "candidate_id": "generic-probe",
                        "source_retained": "generic-probe.c",
                        "target_score": _sort_real_target_score(
                            actual34=27,
                            actual44=25,
                        ),
                        "structural_guard": {"accepted": True},
                    }
                ],
            }
        ],
    )

    assert not [
        row
        for row in payload["ranked_retained_candidates"]
        if row.get("source") == "select-order"
    ]
    assert any(
        row["status"] == "unrecognized" for row in payload["continuation_artifacts"]
    )
    assert "unrecognized-continuation-artifact" in payload["terminal_blockers"]


def test_sort_continuation_emits_protected_loss_repair_lane() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_combine_real_score_protected_loss_terminal()],
    )

    assert payload["status"] == "actionable"
    assert payload["terminal"] is False
    assert payload["accepted_candidates"] == []
    continuation = payload["continuation"]
    assert continuation["route"] == "sort-semantic-protected-loss-repair"
    assert continuation["candidate_id"] == "repair-selected-name-owner-dst"
    assert continuation["source_retained"] == (
        "build/sort/repair-selected-name-owner-dst.c"
    )
    assert continuation["pcdump_path"] == (
        "build/sort/repair-selected-name-owner-dst.pcdump.txt"
    )
    assert continuation["missing_protected_assignments"] == [{"ig": 34, "phys": 27}]
    assert continuation["satisfied_protected_assignments"] == [{"ig": 44, "phys": 25}]
    assert continuation["protected_assignments_satisfied"] is False
    assert continuation["source_hunks"] == [
        _sort_semantic_hunk(10),
        _sort_semantic_hunk(30),
    ]
    assert continuation["source_components"] == [
        _sort_semantic_component("sort-loop-ownership"),
        _sort_semantic_component("sort-selected-name-extraction"),
    ]
    assert all(isinstance(row, dict) for row in continuation["next_actions"])
    assert "debug target score-source" in continuation["command"]
    ranked = payload["ranked_retained_candidates"]
    repair = next(
        row
        for row in ranked
        if row.get("candidate_id") == "repair-selected-name-owner-dst"
    )
    assert repair["repair_actionable"] is True
    assert repair["accepted"] is False
    assert repair["source_hunks"] == continuation["source_hunks"]


def test_sort_post_inline_one_hit_split_emits_protected_continuation_lane() -> None:
    payload = build_source_family_continuation_payload(
        _sort_post_inline_one_hit_classified(),
        [_sort_post_inline_raw_combine_one_hit()],
    )

    assert payload["status"] == "actionable"
    assert payload["terminal"] is False
    continuation = payload["continuation"]
    assert continuation["route"] == SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
    assert continuation["candidate_id"] == (
        "combine-post-inline-ig34-ig44-lower-drift"
    )
    assert continuation["source_retained"].endswith(".c")
    assert continuation["pcdump_path"].endswith(".pcdump.txt")
    assert continuation["satisfied_protected_assignments"] == [
        {"ig": 44, "phys": 25}
    ]
    assert continuation["missing_protected_assignments"] == [
        {"ig": 34, "phys": 27}
    ]
    assert continuation["source_model_layer_dimension_id"] == (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
    )
    assert "debug target score-source" in continuation["command"]

    semantic = payload["semantic_recombine"]
    assert semantic["status"] == "terminal"
    assert not [
        row
        for row in semantic["ranked_candidates"]
        if row.get("accepted") is True
        and isinstance(row.get("target_score"), dict)
        and row["target_score"].get("estimated") is True
    ]
    assert (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_BLOCKER
        in payload["terminal_blockers"]
    )
    search_summary = next(
        row for row in payload["continuation_artifacts"] if row["kind"] == "search-combine"
    )
    assert (
        "one-hit-recombine-protected-targets-not-jointly-preserved"
        in search_summary["terminal_blockers"]
    )
    synthesis_proof = payload["source_model_proof"]["source_family_synthesis"]
    assert synthesis_proof["semantic_recombine"] == semantic
    assert {
        "post-meta-source-family-sort-init-indexed-write-name-total-locals",
        "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
    } <= {
        row["candidate_id"] for row in synthesis_proof["retained_scored_probes"]
    }


def test_sort_post_inline_one_hit_split_terminal_names_missing_source_family_without_route() -> None:
    payload = build_source_family_continuation_payload(
        _sort_post_inline_one_hit_classified(),
        [_sort_post_inline_raw_combine_one_hit(include_route=False)],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert payload["score_classification"]["best_target_matched"] == 1
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    proof = payload["source_model_proof"]
    synthesis_proof = proof["source_family_synthesis"]
    assert synthesis_proof["next_unsupported_source_family"] == (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert {
        "post-meta-source-family-sort-init-indexed-write-name-total-locals",
        "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
    } <= {
        row["candidate_id"] for row in synthesis_proof["retained_scored_probes"]
    }
    assert (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_BLOCKER
        in payload["terminal_blockers"]
    )
    search_summary = next(
        row for row in payload["continuation_artifacts"] if row["kind"] == "search-combine"
    )
    assert (
        "one-hit-recombine-protected-targets-not-jointly-preserved"
        in search_summary["terminal_blockers"]
    )
    assert synthesis_proof["semantic_recombine"]["status"] == "terminal"


def test_sort_protected_loss_repair_lane_reaches_retained_allocator(
    tmp_path: Path,
) -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_combine_real_score_protected_loss_terminal()],
    )
    artifact = tmp_path / "sort-protected-loss-continuation.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )
    next_frontier = triaged["functions"][0]["frontiers"][0]

    assert next_frontier["status"] == "actionable"
    assert next_frontier["family_id"] == "post-ceiling-source-model-proof"
    assert next_frontier["continuation"]["route"] == (
        "sort-semantic-protected-loss-repair"
    )
    assert next_frontier["continuation"]["pcdump_path"].endswith(".pcdump.txt")
    assert next_frontier["continuation"]["missing_protected_assignments"] == [
        {"ig": 34, "phys": 27}
    ]

    ceiling = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)
    assert ceiling["status"] == "actionable"
    assert ceiling["terminal_reason"] == (
        "retained-frontiers-next-source-actionable-lane"
    )
    assert any(
        "repair-selected-name-owner-dst.c" in step for step in ceiling["next_steps"]
    )


def test_sort_semantic_commandless_source_hunks_needs_real_score(
    tmp_path: Path,
) -> None:
    rows = [
        _sort_one_hit_row(
            "post-meta-sort-semantic-owner-dst-local-only",
            "sort-semantic-loop-ownership",
            hit_virtual="34",
            hunk_start=10,
            component_id="sort-loop-ownership",
            source_retained="ig34.c",
        ),
        _sort_one_hit_row(
            "post-meta-sort-semantic-selected-name-after-inner",
            "sort-semantic-selected-name-extraction",
            hit_virtual="44",
            hunk_start=20,
            component_id="sort-selected-name-extraction",
            source_retained="ig44.c",
        ),
    ]
    continuation_payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(rows),
        [],
    )
    assert continuation_payload["status"] == "blocked"
    assert continuation_payload["terminal"] is False
    assert continuation_payload["continuation"] is None
    proposal = continuation_payload["semantic_recombine"]["ranked_candidates"][0]
    assert proposal["accepted"] is False
    assert proposal["source_hunks"]
    assert "no-scored-recombine-evidence" in proposal["blockers"]

    artifact = tmp_path / "sort-semantic-recombine-continuation.json"
    artifact.write_text(json.dumps(continuation_payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )
    assert triaged["status"] == "all-known-frontiers-exhausted"
    assert triaged["functions"][0]["frontiers"] == []

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)
    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling"
    )
    assert not any("source hunk" in step for step in result["next_steps"])


def test_sort_continuation_real_score_terminal_when_no_repair_seed() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_combine_real_score_protected_loss_terminal(include_repair_seed=False)],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    dimensions = {row["dimension_id"] for row in payload["exhausted_dimensions"]}
    assert SORT_SEMANTIC_RECOMBINE_DIMENSION in dimensions
    assert "sort-semantic-protected-loss-repair" in dimensions
    attempts = payload["source_model_proof"]["source_family_synthesis"][
        "continuation_attempts"
    ]
    protected_summary = next(
        row for row in attempts if row["kind"] == "protected-structural-synthesis"
    )
    assert protected_summary["status"] == "terminal-component-subset-exhausted"
    assert protected_summary["ranked_candidates"][0]["target_score"]["matched"] == 1
    assert protected_summary["ranked_candidates"][0]["source_hunks"] == [
        _sort_semantic_hunk(10),
        _sort_semantic_hunk(30),
    ]
    assert {
        "lower-drift-candidates-lost-protected-assignments",
        "recombine-overlapping-source-hunks",
        "protected-structural-synthesis-exhausted",
    } <= set(payload["terminal_blockers"])


def test_manual_subhunk_lost_both_is_negative_evidence_not_repair_route() -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [
            _sort_combine_real_score_protected_loss_terminal(),
            _sort_manual_subhunk_protected_loss_terminal(),
        ],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert "manual-subhunk-protected-loss-exhausted" in payload["terminal_blockers"]
    evidence = payload["protected_loss_negative_evidence"]
    assert evidence["reason"] == "manual-subhunk-protected-loss-exhausted"
    assert evidence["exhausted_candidate_count"] == 3
    ranked = payload["ranked_retained_candidates"]
    manual = [
        row
        for row in ranked
        if str(row.get("candidate_id", "")).startswith("combine-init-")
        and row.get("dimension_id") == SORT_SEMANTIC_PROTECTED_LOSS_REPAIR_DIMENSION
    ]
    assert manual
    assert all(row["negative_evidence_only"] is True for row in manual)
    assert all(row["repair_actionable"] is False for row in manual)
    original = next(
        row
        for row in ranked
        if row.get("candidate_id") == "repair-selected-name-owner-dst"
    )
    assert original["repair_actionable"] is False
    assert original["superseded_by_negative_evidence"] is True
    attempts = payload["source_model_proof"]["source_family_synthesis"][
        "continuation_attempts"
    ]
    assert (
        sum(1 for row in attempts if row["kind"] == "protected-structural-synthesis")
        == 2
    )
    assert (
        "lower-drift-preserving init-lifetime"
        in payload["next_unsupported_source_model"]
    )
    assert payload["real_score_authority"] == "protected-loss-negative-evidence"
    assert payload["suppressed_estimated_candidate_ids"]
    assert payload["superseded_estimated_pairs"]
    assert "real-score-protected-loss" in payload["terminal_blockers"]


def _lower_drift_terminal_with_seed(tmp_path: Path) -> tuple[dict, Path]:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [
            _sort_combine_real_score_protected_loss_terminal(),
            _sort_manual_subhunk_protected_loss_terminal(),
        ],
    )
    seed = tmp_path / "build" / "sort" / "lower-drift-ig44-seed.c"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text(_sort_protected_loss_seed_source(), encoding="utf-8")
    for row in payload["ranked_retained_candidates"]:
        if row.get("candidate_id") == "repair-selected-name-owner-dst":
            row["source_retained"] = str(seed)
            row["path"] = str(seed)
            row["candidate_path"] = str(seed)
            break
    return payload, seed


def test_sort_lower_drift_init_lifetime_generation_from_terminal_next_lever(
    tmp_path: Path,
) -> None:
    terminal, _seed = _lower_drift_terminal_with_seed(tmp_path)
    context = normalize_meta_ceiling_context(
        [terminal],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=8,
        include_source=True,
    )

    lower_drift = [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION
    ]
    assert lower_drift
    assert len(candidates) > len(
        [
            row
            for row in candidates
            if row["dimension_id"] in OLD_SORT_DIMENSIONS | NATURAL_SORT_DIMENSIONS
        ]
    )
    assert all(
        row["validation_metadata"]["lower_drift_init_lifetime"] is True
        for row in lower_drift
    )
    assert all(
        "IG44->r25" in row["validation_metadata"]["required_preserved_assignments"]
        for row in lower_drift
    )
    assert all(
        "IG34->r27" in row["validation_metadata"]["required_recovered_assignments"]
        for row in lower_drift
    )
    assert all("post_ceiling_j_text_copy" in row["source_text"] for row in lower_drift)
    assert any(
        "mnDiagram_SumNameKOs(post_meta_name_byte)" in row["source_text"]
        for row in lower_drift
    )
    assert {
        "sort-init-region",
        "sort-ig34-name-byte-total-materialization",
        "sort-ig44-predicate-local-copy-block",
    } <= {
        component["component_id"]
        for row in lower_drift
        for component in row["source_components"]
    }
    assert all(
        "post_ceiling_j_text_copy"
        not in "\n".join(
            line
            for hunk in row.get("source_hunks", [])
            for line in [*hunk.get("removed", []), *hunk.get("added", [])]
        )
        for row in lower_drift
    )


def test_sort_lower_drift_init_lifetime_generation_blocker_when_no_ig44_seed(
    tmp_path: Path,
) -> None:
    terminal = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [
            _sort_combine_real_score_protected_loss_terminal(),
            _sort_manual_subhunk_protected_loss_terminal(),
        ],
    )
    context = normalize_meta_ceiling_context(
        [terminal],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=2,
        include_source=True,
    )

    payload = build_generated_source_family_payload(candidates, context)
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"] == synthesis.SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION
    )

    assert dimension["status"] == "blocked"
    assert dimension["candidate_count"] == 0
    assert any(
        blocker["reason"]
        == synthesis.SORT_PROTECTED_LOSS_INIT_LIFETIME_SOURCE_REGION_PATTERN_BLOCKER
        for blocker in dimension["blockers"]
    )


def test_sort_lower_drift_init_lifetime_classifier_requires_joint_targets(
    tmp_path: Path,
) -> None:
    terminal, _seed = _lower_drift_terminal_with_seed(tmp_path)
    context = normalize_meta_ceiling_context(
        [terminal],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    candidate = next(
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_PROTECTED_LOSS_INIT_LIFETIME_DIMENSION
    )

    ig34_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=22, accepted=True)],
        context,
    )
    assert ig34_only["status"] == "terminal"
    assert {
        "protected-targets-not-jointly-preserved",
        "required-assignment-not-preserved:IG44->r25",
    } <= set(ig34_only["score_rows"][0]["blockers"])
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in ig34_only["terminal_blockers"]
    )

    ig44_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=24, actual44=25, accepted=True)],
        context,
    )
    assert ig44_only["status"] == "terminal"
    assert (
        "required-assignment-not-recovered:IG34->r27"
        in ig44_only["score_rows"][0]["blockers"]
    )

    both = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=25, accepted=True)],
        context,
    )
    assert both["status"] == "actionable"
    assert both["ranked_candidates"][0]["candidate_id"] == candidate["candidate_id"]


def test_sort_full_selection_swap_generation_from_terminal_next_model() -> None:
    context = _sort_full_selection_swap_context()

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        include_source=True,
    )
    full_selection = [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]

    assert {
        "post-meta-sort-full-selection-full-selection-swap-carried-combined",
        "post-meta-sort-full-selection-full-selection-loop-carried-state",
        "post-meta-sort-full-selection-full-comparison-state-latched",
        "post-meta-sort-full-selection-full-selected-name-stable-local",
        "post-meta-sort-full-selection-full-swap-emission-pointer-walk",
    } == {row["candidate_id"] for row in full_selection}
    assert all(row["source_hunks"] for row in full_selection)
    assert all(
        row["validation_metadata"]["full_selection_swap_source_model"] is True
        for row in full_selection
    )
    assert all(
        row["validation_metadata"]["semantic_algorithm_shape"] is True
        for row in full_selection
    )
    assert all(
        row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in full_selection
    )
    assert set(synthesis.SORT_FULL_SELECTION_SWAP_COMPONENTS) <= {
        component["component_id"]
        for row in full_selection
        for component in row["source_components"]
    }
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        for row in full_selection
    )
    assert all(
        row["validation_metadata"]["requires_structural_guard"] is True
        for row in full_selection
    )
    assert all(
        "--full-unit-source" in row["validation_metadata"]["score_source_command_hint"]
        for row in full_selection
    )


def test_sort_full_selection_swap_materializes_from_retained_pointer_loop_seed() -> None:
    context = _sort_full_selection_swap_context()
    seed_source = _sort_retained_pointer_loop_seed_source()
    seed = {
        "candidate_id": "post-meta-sort-semantic-recombine-retained-pointer-loop",
        "family": synthesis.SORT_SEMANTIC_RECOMBINE_DIMENSION,
        "source_text": seed_source,
        "satisfied_protected_assignments": [{"ig": 44, "phys": 25}],
        "target_score": _sort_real_target_score(actual34=28, actual44=25),
        "structural_guard": {"accepted": True},
    }
    context = replace(
        context,
        current_ceiling={
            **context.current_ceiling,
            "ranked_candidates": [seed],
        },
    )
    nonmaterializable_source = _sort_source().replace(
        "for (i = 0; i < 0x78; i++)",
        "for (i = 0; i < 0x77; i++)",
        1,
    )

    candidates = generate_source_family_candidates(
        nonmaterializable_source,
        context,
        max_per_dimension=10,
        include_source=True,
    )
    full_selection = [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]

    assert full_selection
    assert all(
        row["validation_metadata"]["retained_pointer_loop_seed"] is True
        for row in full_selection
    )
    assert all(
        row["validation_metadata"]["seed_candidate_id"]
        == "post-meta-sort-semantic-recombine-retained-pointer-loop"
        for row in full_selection
    )
    assert all("post_meta_selected_name" in row["source_text"] for row in full_selection)
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        and row["validation_metadata"]["requires_structural_guard"] is True
        and row["validation_metadata"]["requires_target_score_validation"] is True
        for row in full_selection
    )


def test_sort_full_selection_swap_materializes_from_retained_pointer_source() -> None:
    context = _sort_full_selection_swap_context()

    candidates = generate_source_family_candidates(
        _sort_retained_pointer_seed_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    full_selection = [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]

    assert {
        "post-meta-sort-full-selection-full-selection-swap-carried-combined",
        "post-meta-sort-full-selection-full-selection-loop-carried-state",
        "post-meta-sort-full-selection-full-comparison-state-latched",
        "post-meta-sort-full-selection-full-selected-name-stable-local",
        "post-meta-sort-full-selection-full-swap-emission-pointer-walk",
    } == {row["candidate_id"] for row in full_selection}
    assert all(
        row["source_function"] == synthesis.SORT_FUNCTION for row in full_selection
    )
    assert all(row["source_hunks"] for row in full_selection)
    assert all("ll_probe_iter_0" not in row["source_text"] for row in full_selection)
    assert any(
        "post_meta_candidate_name = sorted_names[j];" in row["source_text"]
        for row in full_selection
    )
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        for row in full_selection
    )
    assert all(
        "--full-unit-source" in row["score_source_command_hint"]
        for row in full_selection
    )


def test_sort_full_selection_swap_retained_pointer_requires_final_write() -> None:
    context = _sort_full_selection_swap_context()
    source = _sort_retained_pointer_seed_source().replace(
        "*ll_probe_iter_0 = temp;",
        "temp = *ll_probe_iter_0;",
    )

    candidates = generate_source_family_candidates(
        source,
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert not [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]
    payload = build_generated_source_family_payload(candidates, context)
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    )
    assert any(
        blocker["reason"]
        == synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
        for blocker in dimension["blockers"]
    )


def test_sort_full_selection_swap_stage_suppresses_prior_sort_families() -> None:
    context = _sort_full_selection_swap_context()

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    payload = build_generated_source_family_payload(candidates, context)

    assert candidates
    assert {row["dimension_id"] for row in candidates} == {
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    }
    assert [row["dimension_id"] for row in payload["dimensions"]] == [
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]


def test_sort_full_selection_swap_zero_candidates_report_blocker() -> None:
    context = _sort_full_selection_swap_context()
    source = _sort_source().replace(
        "for (j = i + 1; j < 0x78; j++)",
        "for (j = i + 2; j < 0x78; j++)",
    )
    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
    )

    assert not [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]

    payload = build_generated_source_family_payload(candidates, context)
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    )

    assert dimension["status"] == "blocked"
    assert dimension["candidate_count"] == 0
    assert any(
        blocker["reason"]
        == synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
        for blocker in dimension["blockers"]
    )
    assert (
        list(synthesis.SORT_FULL_SELECTION_SWAP_REQUIRED_SOURCE_PATTERNS)
        == dimension["blockers"][0]["required_patterns"]
    )


def test_sort_full_selection_swap_classifier_names_next_source_family() -> None:
    context = _sort_full_selection_swap_context()
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    full_selection = [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]

    payload = classify_source_family_scores(
        full_selection,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in full_selection
        ],
        context,
    )

    assert payload["status"] == "terminal"
    assert (
        payload["next_unsupported_source_model"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL
    )
    assert (
        payload["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["next_unsupported_source_spans"]
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in payload["terminal_blockers"]
    )

    actionable = classify_source_family_scores(
        full_selection,
        [
            _score(candidate, actual34=27, actual44=25, accepted=True)
            for candidate in full_selection
        ],
        context,
    )
    assert actionable["status"] == "actionable"


def _sort_full_selection_swap_terminal_payload() -> dict:
    context = _sort_full_selection_swap_context()
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    full_selection = [
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]
    return classify_source_family_scores(
        full_selection,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in full_selection
        ],
        context,
    )


def _sort_whole_function_control_data_flow_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_full_selection_swap_terminal_payload()],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_whole_function_control_data_flow_terminal_payload(tmp_path: Path) -> dict:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    whole_function = [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]
    return classify_source_family_scores(
        whole_function,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in whole_function
        ],
        context,
    )


def _sort_helper_data_layout_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_whole_function_control_data_flow_terminal_payload(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_helper_data_layout_context_terminal_payload(tmp_path: Path) -> dict:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    return classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in candidates
        ],
        context,
    )


def _sort_tu_source_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_helper_data_layout_context_terminal_payload(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_unbounded_tu_data_ownership_context(tmp_path: Path):
    context = _sort_tu_source_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    terminal = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=24, actual44=None, accepted=True)
            for candidate in candidates
        ],
        context,
    )
    return normalize_meta_ceiling_context(
        [terminal],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_unbounded_tu_data_ownership_terminal_payload(tmp_path: Path) -> dict:
    context = _sort_unbounded_tu_data_ownership_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    actuals = [(25, None), (24, None), (24, 31)]
    return classify_source_family_scores(
        candidates,
        [
            _score(
                candidate,
                actual34=actuals[index % len(actuals)][0],
                actual44=actuals[index % len(actuals)][1],
                accepted=True,
            )
            for index, candidate in enumerate(candidates)
        ],
        context,
    )


def _sort_post_cross_tu_terminal_proof() -> dict:
    rows = [
        _sort_one_hit_row(
            "post-cross-tu-ig34-retained",
            synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
            hit_virtual="34",
            hunk_start=930,
            component_id="sort-cross-tu-linkage",
            source_retained="/tmp/post-cross-tu-ig34.c",
        ),
        _sort_one_hit_row(
            "post-cross-tu-ig44-retained",
            synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
            hit_virtual="44",
            hunk_start=940,
            component_id="sort-data-section-ownership",
            source_retained="/tmp/post-cross-tu-ig44.c",
        ),
    ]
    for index, row in enumerate(rows):
        row["pcdump_path"] = f"/tmp/post-cross-tu-{index}.pcdump.txt"
        row["source_model_layer_dimension_id"] = (
            synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
        )
        row["cross_tu_symbol_linkage_source_context_model"] = True
    source_hunks_by_candidate = [
        {
            "candidate_id": row["candidate_id"],
            "dimension_id": synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
            "source_hunks": list(row.get("source_hunks") or []),
            "source_components": list(row.get("source_components") or []),
        }
        for row in rows
    ]
    exhausted_dimensions = [
        {
            "dimension_id": synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": (
                "one-hit-recombine-protected-targets-not-jointly-preserved"
            ),
        }
    ]
    one_hit_summary = {
        "one_hit_targets": ["34", "44"],
        "best_by_target": {
            "34": {"candidate_id": rows[0]["candidate_id"]},
            "44": {"candidate_id": rows[1]["candidate_id"]},
        },
        "best_joint_candidate": None,
        "protected_targets_not_jointly_preserved": True,
    }
    return {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "allocator_facts": [
            {"virtual": 34, "expected": 27, "actual": 24, "name": "ig34"},
            {"virtual": 44, "expected": 25, "actual": 27, "name": "ig44"},
        ],
        "source_spans": list(_current_ceiling()["source_spans"]),
        "candidate_scores": rows,
        "attempted_equivalence_classes": [
            synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
        ],
        "next_unsupported_source_model": (
            synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
        ),
        "next_unsupported_source_family": (
            synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
        ),
        "terminal_blockers": [synthesis.SORT_CROSS_TU_ONE_HIT_TERMINAL_BLOCKER],
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "evidence_status": "artifact-score-rows",
            "forced_target_map": {"34": 27, "44": 25},
            "attempted_equivalence_classes": [
                synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
            ],
            "exhausted_dimensions": exhausted_dimensions,
            "source_hunks_by_candidate": source_hunks_by_candidate,
            "retained_scored_probes": rows,
            "candidate_scores": rows,
            "scored_count": len(rows),
            "next_unsupported_source_model": (
                synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
            ),
            "next_unsupported_source_family": (
                synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
            ),
            "one_hit_summary": one_hit_summary,
            "terminal_blockers": [synthesis.SORT_CROSS_TU_ONE_HIT_TERMINAL_BLOCKER],
        },
    }


def _sort_post_cross_tu_allocator_payload() -> dict:
    return {
        "function": SORT_FUNCTION,
        "status": "practical-ceiling",
        "current_ceiling": {"status": "complete"},
        "retained_frontiers_meta_ceiling": {
            "closed_families": ["post-ceiling-source-model-proof"],
            "terminal_proof": _sort_post_cross_tu_terminal_proof(),
        },
    }


def _strip_next_unsupported_source_family(value):
    if isinstance(value, dict):
        return {
            key: _strip_next_unsupported_source_family(item)
            for key, item in value.items()
            if key != "next_unsupported_source_family"
        }
    if isinstance(value, list):
        return [_strip_next_unsupported_source_family(item) for item in value]
    return value


def _sort_post_cross_tu_model_only_allocator_payload() -> dict:
    return _strip_next_unsupported_source_family(_sort_post_cross_tu_allocator_payload())


def _sort_post_cross_tu_protected_targets_only_allocator_payload() -> dict:
    payload = json.loads(json.dumps(_sort_post_cross_tu_allocator_payload()))
    proof = payload["retained_frontiers_meta_ceiling"]["terminal_proof"]
    proof["terminal_blockers"] = ["protected-targets-not-jointly-preserved"]
    synthesis_proof = proof["source_family_synthesis"]
    synthesis_proof.pop("one_hit_summary", None)
    synthesis_proof["terminal_blockers"] = ["protected-targets-not-jointly-preserved"]
    return payload


def _sort_post_cross_tu_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_post_cross_tu_allocator_payload()],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_post_cross_tu_model_only_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_post_cross_tu_model_only_allocator_payload()],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_post_cross_tu_protected_targets_only_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_post_cross_tu_protected_targets_only_allocator_payload()],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def test_sort_full_selection_swap_terminal_continuation_preserves_next_family() -> None:
    payload = build_source_family_continuation_payload(
        _sort_full_selection_swap_terminal_payload(),
        [],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert payload["accepted_candidates"] == []
    assert (
        payload["next_unsupported_source_model"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL
    )
    assert (
        payload["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
        not in (payload["terminal_blockers"])
    )
    assert not [
        row
        for row in payload.get("blocked_dimensions") or []
        if row.get("dimension_id") == synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
    ]

    proof = payload["source_model_proof"]
    proof_synthesis = proof["source_family_synthesis"]
    assert (
        proof["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        proof_synthesis["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
        in (proof_synthesis["attempted_equivalence_classes"])
    )


def test_sort_raw_full_selection_swap_scored_continuation_names_whole_function_family() -> None:
    classified = _sort_one_hit_classified_with_rows(
        [
            _sort_one_hit_row(
                "post-meta-sort-full-selection-full-comparison-state-latched",
                synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION,
                hit_virtual="34",
                hunk_start=40,
                component_id="sort-full-comparison-state",
                source_retained=(
                    "build/diagnostics/sort_full_selection_swap/"
                    "post-meta-sort-full-selection-full-comparison-state-latched.c"
                ),
            ),
            _sort_one_hit_row(
                "post-meta-sort-full-selection-full-selected-name-stable-local",
                synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION,
                hit_virtual="44",
                hunk_start=64,
                component_id="sort-full-selected-name",
                source_retained=(
                    "build/diagnostics/sort_full_selection_swap/"
                    "post-meta-sort-full-selection-full-selected-name-stable-local.c"
                ),
            ),
        ]
    )

    payload = build_source_family_continuation_payload(classified, [])

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert (
        payload["next_unsupported_source_model"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL
    )
    assert (
        payload["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
        not in payload["terminal_blockers"]
    )
    assert payload["next_unsupported_source_spans"]
    assert {
        row["dimension_id"] for row in payload["next_unsupported_source_spans"]
    } == {synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION}

    proof = payload["source_model_proof"]
    proof_synthesis = proof["source_family_synthesis"]
    assert (
        proof["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        proof_synthesis["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
        in proof_synthesis["attempted_equivalence_classes"]
    )


def test_sort_raw_full_selection_swap_joint_hit_stays_actionable() -> None:
    row = _sort_one_hit_row(
        "post-meta-sort-full-selection-joint-hit",
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION,
        hit_virtual="34",
        hunk_start=40,
        component_id="sort-full-comparison-state",
        source_retained=(
            "build/diagnostics/sort_full_selection_swap/"
            "post-meta-sort-full-selection-joint-hit.c"
        ),
    )
    row["target_matched"] = 2
    row["target_virtual_distance"] = 0
    row["target_score"]["matched"] = 2
    row["target_score"]["virtual_distance"] = 0
    row["target_score"]["virtuals"]["44"]["actual"] = 25
    row["target_score"]["virtuals"]["44"]["matched"] = True
    row["structural_guard"]["accepted"] = True
    row["structural_guard_accepted"] = True
    classified = _sort_one_hit_classified_with_rows([row])

    payload = build_source_family_continuation_payload(classified, [])

    assert payload["status"] == "actionable"
    assert payload["terminal"] is False
    assert payload["continuation"]["source_retained"] == row["source_retained"]
    assert "next_unsupported_source_family" not in payload


def test_sort_raw_full_selection_swap_incomplete_or_error_rows_do_not_terminalize() -> None:
    error_row = _sort_one_hit_row(
        "post-meta-sort-full-selection-score-error",
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION,
        hit_virtual="34",
        hunk_start=40,
        component_id="sort-full-comparison-state",
        source_retained=(
            "build/diagnostics/sort_full_selection_swap/"
            "post-meta-sort-full-selection-score-error.c"
        ),
    )
    error_row["score_error"] = "compile-error"
    error_payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows([error_row]),
        [],
    )

    assert error_payload["status"] == "blocked"
    assert error_payload["terminal"] is False
    assert "next_unsupported_source_family" not in error_payload

    incomplete = _sort_one_hit_classified_with_rows(
        [
            _sort_one_hit_row(
                "post-meta-sort-full-selection-missing-score",
                synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION,
                hit_virtual="44",
                hunk_start=64,
                component_id="sort-full-selected-name",
                source_retained=(
                    "build/diagnostics/sort_full_selection_swap/"
                    "post-meta-sort-full-selection-missing-score.c"
                ),
            )
        ]
    )
    incomplete["candidate_count"] = 2
    incomplete["score_count"] = 1
    incomplete["missing_score_candidate_ids"] = [
        "post-meta-sort-full-selection-unscored"
    ]
    incomplete_payload = build_source_family_continuation_payload(incomplete, [])

    assert incomplete_payload["status"] == "blocked"
    assert incomplete_payload["terminal"] is False
    assert "next_unsupported_source_family" not in incomplete_payload


def test_sort_whole_function_control_data_flow_generation_from_full_selection_terminal(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    context = replace(
        context,
        current_ceiling={
            **context.current_ceiling,
            "prior_natural_rewrite_evidence": [
                *synthesis.SOURCE_FAMILY_DIMENSIONS,
                "sort-one-hit-structural-repair",
                "sort-one-hit-recombination",
            ],
        },
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        include_source=True,
        max_per_dimension=10,
    )
    whole_function = [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]

    assert {row["dimension_id"] for row in candidates} == {
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    }
    assert {
        "post-meta-sort-whole-function-source-owner-unified",
        "post-meta-sort-whole-function-selected-record-carried",
        "post-meta-sort-whole-function-selected-name-total-carried",
        "post-meta-sort-whole-function-shift-emission-indexed",
        "post-meta-sort-whole-function-prefix-insertion-rebuild",
    } == {row["candidate_id"] for row in whole_function}
    assert all(row["source_hunks"] for row in whole_function)
    assert all(
        "void mnDiagram_8023FC28(void)" in row["source_text"] for row in whole_function
    )
    assert all(
        row["validation_metadata"]["whole_function_control_data_flow_source_model"]
        is True
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["semantic_algorithm_shape"] is True
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["requires_structural_guard"] is True
        for row in whole_function
    )
    assert all(
        "--full-unit-source"
        in row["validation_metadata"]["score_source_command_hint"]
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in whole_function
    )
    component_ids = {
        component["component_id"]
        for row in whole_function
        for component in row["source_components"]
    }
    assert set(synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_COMPONENTS) <= (
        component_ids
    )


def test_sort_whole_function_control_data_flow_materializes_from_retained_pointer_source(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_retained_pointer_seed_source(),
        context,
        include_source=True,
        max_per_dimension=10,
    )
    whole_function = [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]

    assert {
        "post-meta-sort-whole-function-source-owner-unified",
        "post-meta-sort-whole-function-selected-record-carried",
        "post-meta-sort-whole-function-selected-name-total-carried",
        "post-meta-sort-whole-function-shift-emission-indexed",
        "post-meta-sort-whole-function-prefix-insertion-rebuild",
    } == {row["candidate_id"] for row in whole_function}
    assert len(whole_function) == 5
    assert all(
        row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
        for row in whole_function
    )
    assert all(row["source_hunks"] for row in whole_function)
    assert all(
        row["validation_metadata"]["whole_function_control_data_flow_source_model"]
        is True
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["semantic_algorithm_shape"] is True
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        and row["validation_metadata"]["requires_structural_guard"] is True
        for row in whole_function
    )
    assert all(
        "--full-unit-source" in row["validation_metadata"]["score_source_command_hint"]
        for row in whole_function
    )
    assert all(
        row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in whole_function
    )
    component_ids = {
        component["component_id"]
        for row in whole_function
        for component in row["source_components"]
    }
    assert set(synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_COMPONENTS) <= (
        component_ids
    )
    assert all("ll_probe_iter_0" not in row["source_text"] for row in whole_function)
    assert all(
        "target_repair_live_range_ig39_probe" not in row["source_text"]
        for row in whole_function
    )


def _assert_whole_function_control_data_flow_source_region_blocked(
    candidates: list[dict],
    context,
) -> None:
    payload = build_generated_source_family_payload(candidates, context)
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    )

    assert dimension["status"] == "blocked"
    assert dimension["candidate_count"] == 0
    blocker = dimension["blockers"][0]
    assert (
        blocker["reason"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_SOURCE_REGION_PATTERN_BLOCKER
    )
    assert blocker in payload["generation_blockers"]


def test_sort_whole_function_control_data_flow_zero_candidates_report_blocker(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    source = _sort_source().replace(
        "for (j = i + 1; j < 0x78; j++)",
        "for (j = i + 2; j < 0x78; j++)",
    )
    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
        max_per_dimension=10,
    )

    assert not [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]

    payload = build_generated_source_family_payload(candidates, context)
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    )

    assert dimension["status"] == "blocked"
    assert dimension["candidate_count"] == 0
    blocker = dimension["blockers"][0]
    expected_reason = (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_SOURCE_REGION_PATTERN_BLOCKER
    )
    assert blocker["reason"] == expected_reason
    assert blocker["required_patterns"] == list(
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_REQUIRED_SOURCE_PATTERNS
    )
    assert blocker["trigger_next_unsupported_source_family"] == (
        synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert blocker in payload["generation_blockers"]


def test_sort_whole_function_control_data_flow_retained_pointer_requires_final_write(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    source = _sort_retained_pointer_seed_source().replace(
        "*ll_probe_iter_0 = temp;",
        "temp = *ll_probe_iter_0;",
    )

    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
        max_per_dimension=10,
    )

    assert not [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]
    _assert_whole_function_control_data_flow_source_region_blocked(
        candidates,
        context,
    )


def test_sort_whole_function_control_data_flow_retained_pointer_requires_outer_iterator_write(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    source = _sort_retained_pointer_seed_source().replace(
        "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {\n"
        "            max_idx = i;",
        "for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {\n"
        "            u8* wrong_emit = ll_probe_iter_0;\n"
        "            max_idx = i;",
    )
    source = source.replace(
        "*ll_probe_iter_0 = temp;",
        "*wrong_emit = temp;",
    )

    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
        max_per_dimension=10,
    )

    assert not [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]
    _assert_whole_function_control_data_flow_source_region_blocked(
        candidates,
        context,
    )


def test_sort_whole_function_control_data_flow_retained_pointer_requires_init_write(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    source = _sort_retained_pointer_seed_source().replace(
        "*dst_iter = (u8) n;",
        "target_repair_live_range_ig39_probe = (u8) n;",
    )

    candidates = generate_source_family_candidates(
        source,
        context,
        include_source=True,
        max_per_dimension=10,
    )

    assert not [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]
    _assert_whole_function_control_data_flow_source_region_blocked(
        candidates,
        context,
    )


def test_sort_whole_function_control_data_flow_classifier_requires_joint_targets(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    candidate = next(
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    )

    ig34_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=22, accepted=True)],
        context,
    )
    assert ig34_only["status"] == "terminal"
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in ig34_only["terminal_blockers"]
    )

    ig44_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=24, actual44=25, accepted=True)],
        context,
    )
    assert ig44_only["status"] == "terminal"
    assert (
        "required-assignment-not-preserved:IG34->r27"
        in ig44_only["score_rows"][0]["blockers"]
    )

    rejected = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=25, accepted=False)],
        context,
    )
    assert rejected["status"] == "terminal"
    assert any(
        row["reason"] == "structural-guard-not-accepted"
        for row in rejected["terminal_blockers"]
    )

    actionable = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=25, accepted=True)],
        context,
    )
    assert actionable["status"] == "actionable"
    best = actionable["ranked_candidates"][0]
    assert best["source_hunks"]
    assert best["source_components"]


def test_sort_whole_function_control_data_flow_exhaustion_names_next_family(
    tmp_path: Path,
) -> None:
    context = _sort_whole_function_control_data_flow_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    whole_function = [
        row
        for row in candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]
    assert whole_function

    payload = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in candidates
        ],
        context,
    )

    assert payload["status"] == "terminal"
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
        in (proof_synthesis["attempted_equivalence_classes"])
    )
    assert synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    )
    assert (
        "helper extraction, data layout, or cross-function"
        in payload["next_unsupported_source_model"]
    )
    assert payload["next_unsupported_source_spans"]

    next_context = normalize_meta_ceiling_context(
        [payload],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
    next_candidates = generate_source_family_candidates(
        _sort_source(),
        next_context,
        max_per_dimension=10,
        include_source=True,
    )
    assert not [
        row
        for row in next_candidates
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]


def test_sort_helper_data_layout_context_generation_from_whole_function_terminal(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert {row["dimension_id"] for row in candidates} == {
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
    }
    assert {
        "post-meta-sort-source-context-comparison-helper",
        "post-meta-sort-source-context-comparison-helper-split-text-total",
        "post-meta-sort-source-context-shift-emission-helper",
        "post-meta-sort-source-context-sorted-names-accessor",
        "post-meta-sort-source-context-layout-overlay-local",
    } == {row["candidate_id"] for row in candidates}
    assert all(row["source_hunks"] for row in candidates)
    assert all(
        row["source_text"].index("static inline")
        < row["source_text"].index("void mnDiagram_8023FC28(void)")
        or "typedef struct mnDiagram_PostMetaSortLayout"
        in row["source_text"][
            : row["source_text"].index("void mnDiagram_8023FC28(void)")
        ]
        for row in candidates
    )
    assert all(
        row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in candidates
    )
    assert all(
        row["validation_metadata"]["requires_target_score_validation"] is True
        and row["validation_metadata"]["requires_structural_guard"] is True
        for row in candidates
    )
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        for row in candidates
    )
    assert all(
        "--full-unit-source" in row["validation_metadata"]["score_source_command_hint"]
        for row in candidates
    )
    component_ids = {
        component["component_id"]
        for row in candidates
        for component in row["source_components"]
    }
    assert {
        "sort-helper-extraction",
        "sort-data-layout-overlay",
        "sort-cross-function-source-context",
    } <= component_ids


def test_sort_helper_data_layout_placeholder_exhaustion_does_not_block_generation(
    tmp_path: Path,
) -> None:
    reporter = _sort_whole_function_control_data_flow_terminal_payload(tmp_path)
    placeholder = {
        "dimension_id": synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION,
        "status": "continuation-exhausted",
        "candidate_ids": [],
    }
    reporter.setdefault("exhausted_dimensions", []).append(dict(placeholder))
    reporter["source_model_proof"]["source_family_synthesis"].setdefault(
        "exhausted_dimensions",
        [],
    ).append(dict(placeholder))

    context = normalize_meta_ceiling_context(
        [reporter],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates
    dimensions = {row["dimension_id"] for row in candidates}
    assert dimensions == {synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION}
    assert not dimensions & OLD_SORT_DIMENSIONS


def test_sort_helper_data_layout_context_classifier_requires_joint_targets(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    candidate = next(
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
    )

    ig34_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=22, accepted=True)],
        context,
    )
    assert ig34_only["status"] == "terminal"
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in ig34_only["terminal_blockers"]
    )

    actionable = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=25, accepted=True)],
        context,
    )
    assert actionable["status"] == "actionable"
    assert (
        actionable["ranked_candidates"][0]["candidate_id"]
        == (candidate["candidate_id"])
    )

    rejected = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=25, accepted=False)],
        context,
    )
    assert rejected["status"] == "terminal"
    assert any(
        row["reason"] == "structural-guard-not-accepted"
        for row in rejected["terminal_blockers"]
    )


def test_sort_helper_data_layout_compile_errors_terminalize_bounded_family(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    candidate = next(
        row
        for row in candidates
        if row["dimension_id"] == synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
    )

    payload = classify_source_family_scores(
        [candidate],
        [
            {
                "candidate_id": candidate["candidate_id"],
                "function": SORT_FUNCTION,
                "score_function": SORT_FUNCTION,
                "source_file": "/tmp/helper-layout.c",
                "source_retained": "/tmp/helper-layout.c",
                "c_file": "/tmp/helper-layout.c",
                "cflags_from": "src/melee/mn/mndiagram.c",
                "full_unit_source": True,
                "error": "pcdump missing",
                "returncode": 2,
                "stdout_tail": (
                    "### mwcceppc_debug.exe Compiler:\n"
                    "#   Error: identifier redeclared\n"
                ),
            }
        ],
        context,
    )

    assert payload["status"] == "terminal"
    assert (
        payload["next_unsupported_source_family"]
        == synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in proof_synthesis["exhausted_dimensions"]
    }
    retained = proof_synthesis["retained_scored_probes"]
    assert retained[0]["source_hunks"]
    assert retained[0]["source_retained"] == "/tmp/helper-layout.c"
    assert retained[0]["score_error"] == "pcdump missing"
    assert any(
        row["reason"] == "generated-source-unscoreable"
        for row in payload["terminal_blockers"]
    )


def test_sort_helper_data_layout_context_exhaustion_terminalizes(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    payload = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in candidates
        ],
        context,
    )

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_model"] not in {
        synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL,
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL,
    }
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
        in (proof_synthesis["attempted_equivalence_classes"])
    )
    assert set(proof_synthesis["scored_candidate_ids"]) == {
        row["candidate_id"] for row in candidates
    }
    assert proof_synthesis["retained_scored_probes"]
    assert all(
        row["source_hunks"] and row["source_components"]
        for row in proof_synthesis["source_hunks_by_candidate"]
    )


def test_sort_helper_data_layout_context_terminal_continuation_preserves_next_family(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    terminal = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in candidates
        ],
        context,
    )

    payload = build_source_family_continuation_payload(terminal, [])

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["continuation"] is None
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["next_unsupported_source_spans"]


def test_sort_tu_source_context_generation_from_helper_data_layout_terminal(
    tmp_path: Path,
) -> None:
    context = _sort_tu_source_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert {row["dimension_id"] for row in candidates} == {
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
    }
    assert len(candidates) >= 3
    candidate_ids = {row["candidate_id"] for row in candidates}
    assert "post-meta-sort-tu-source-context-storage-overlay-accessor" in candidate_ids
    assert "post-meta-sort-tu-source-context-shared-name-accessor" in candidate_ids
    assert all(row["source_hunks"] for row in candidates)
    assert any(
        hunk.get("new_start", 0)
        < row["source_text"][
            : row["source_text"].index("void mnDiagram_8023FC28(void)")
        ].count("\n")
        for row in candidates
        for hunk in row["source_hunks"]
    )
    component_ids = {
        component["component_id"]
        for row in candidates
        for component in row["source_components"]
    }
    assert {
        "sort-tu-data-symbol",
        "sort-helper-boundary",
        "sort-cross-function-source-context",
    } <= component_ids
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        and row["validation_metadata"]["requires_structural_guard"] is True
        and row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in candidates
    )
    assert any(
        "mnDiagram_PostMetaSortTUStorage" in row["source_text"]
        and row["source_text"].index("mnDiagram_PostMetaSortTUStorage")
        < row["source_text"].index("void mnDiagram_8023FC28(void)")
        for row in candidates
    )
    shared = next(
        row
        for row in candidates
        if row["candidate_id"]
        == "post-meta-sort-tu-source-context-shared-name-accessor"
    )
    assert shared["source_text"].index("mnDiagram_PostMetaSortNamesBase") < (
        shared["source_text"].index("mnDiagram_GetNameByIndex")
    )


def test_sort_tu_source_context_exhaustion_terminalizes(tmp_path: Path) -> None:
    context = _sort_tu_source_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    payload = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=24, actual44=27, accepted=True)
            for candidate in candidates
        ],
        context,
    )

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
        in (proof_synthesis["attempted_equivalence_classes"])
    )
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in payload["terminal_blockers"]
    )
    assert set(proof_synthesis["scored_candidate_ids"]) == {
        row["candidate_id"] for row in candidates
    }


def test_sort_tu_source_context_zero_candidate_generation_terminalizes(
    tmp_path: Path,
) -> None:
    context = _sort_tu_source_context(tmp_path)

    payload = build_generated_source_family_payload([], context)

    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["terminal_summary"]
    assert payload["generation_blockers"][0]["reason"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER
    )
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"]
        == synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
    )
    assert dimension["status"] == "blocked"
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in proof_synthesis["unmaterialized_dimensions"]
    }
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )


def test_cli_source_model_synthesis_writes_tu_source_context_probes(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "sort-helper-data-layout-terminal.json"
    meta.write_text(
        json.dumps(_sort_helper_data_layout_context_terminal_payload(tmp_path)),
        encoding="utf-8",
    )
    source = tmp_path / "sort.c"
    source.write_text(_sort_source(), encoding="utf-8")
    output = tmp_path / "tu-source-context-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(output),
            "--max-per-dimension",
            "10",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] >= 3
    tu_dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"]
        == synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
    )
    assert tu_dimension["candidate_count"] > 0
    paths = [Path(row["candidate_path"]) for row in payload["candidates"]]
    assert all(path.is_file() for path in paths)
    texts = [path.read_text() for path in paths]
    assert any("mnDiagram_PostMetaSortTUStorage" in text for text in texts)
    assert any("mnDiagram_PostMetaSortNamesBase" in text for text in texts)
    shared_text = next(
        text for text in texts if "mnDiagram_PostMetaSortNamesBase" in text
    )
    assert shared_text.index("mnDiagram_PostMetaSortNamesBase") < (
        shared_text.index("mnDiagram_GetNameByIndex")
    )


def test_sort_unbounded_tu_data_ownership_generation_from_tu_terminal(
    tmp_path: Path,
) -> None:
    context = _sort_unbounded_tu_data_ownership_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates
    assert {row["dimension_id"] for row in candidates} == {
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
    }
    assert all(
        row["candidate_id"].startswith("post-meta-sort-unbounded-tu-data-ownership-")
        for row in candidates
    )
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        and row["validation_metadata"]["requires_structural_guard"] is True
        and row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in candidates
    )
    score_hints = [
        row["validation_metadata"]["score_source_command_hint"] for row in candidates
    ]
    assert all("--full-unit-source" in hint for hint in score_hints)
    assert all("--function mnDiagram_8023FC28" in hint for hint in score_hints)
    assert all("--checkdiff-guard" in hint for hint in score_hints)
    assert any(
        "mnDiagram_PostMetaSortUnboundedTUOwner" in row["source_text"]
        and row["source_text"].index("mnDiagram_PostMetaSortUnboundedTUOwner")
        < row["source_text"].index("void mnDiagram_8023FC28(void)")
        for row in candidates
    )
    component_ids = {
        component["component_id"]
        for row in candidates
        for component in row["source_components"]
    }
    assert {
        "sort-whole-tu-data-declaration",
        "sort-tu-data-ownership",
        "sort-nonlocal-source-ownership",
    } <= component_ids


def test_sort_unbounded_tu_data_ownership_real_source_declaration_order_guard(
    tmp_path: Path,
) -> None:
    source_text = Path("src/melee/mn/mndiagram.c").read_text(encoding="utf-8")
    sort_index = source_text.index("void mnDiagram_SortNamesByKOs(void)")
    assert source_text.index("mnDiagram_804A0750_t mnDiagram_804A0750;") < sort_index
    assert source_text.index("mnDiagram_804A076C_t mnDiagram_804A076C;") < sort_index


def test_sort_unbounded_tu_data_ownership_exhaustion_terminalizes(
    tmp_path: Path,
) -> None:
    payload = _sort_unbounded_tu_data_ownership_terminal_payload(tmp_path)

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
    )
    assert synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
        in (proof_synthesis["attempted_equivalence_classes"])
    )
    assert proof_synthesis["retained_scored_probes"]
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in payload["terminal_blockers"]
    )


def test_sort_unbounded_tu_cross_tu_handoff_does_not_regenerate_lower_families(
    tmp_path: Path,
) -> None:
    terminal = _sort_unbounded_tu_data_ownership_terminal_payload(tmp_path)
    context = normalize_meta_ceiling_context(
        [terminal],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    assert context.next_unsupported_source_family == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )
    payload = build_generated_source_family_payload(
        candidates,
        context,
        continue_after_final_source_family=True,
    )

    assert candidates == []
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["source_model_proof"]["source_family_synthesis"][
        "exhausted_source_dimension"
    ] == synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
    assert payload["generation_blockers"][0]["trigger_next_unsupported_source_family"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert not {row.get("dimension_id") for row in payload.get("candidates", [])} & (
        OLD_SORT_DIMENSIONS | NATURAL_SORT_DIMENSIONS | SEMANTIC_SORT_DIMENSIONS
    )


def test_sort_unbounded_tu_data_ownership_zero_candidate_generation_terminalizes(
    tmp_path: Path,
) -> None:
    context = _sort_unbounded_tu_data_ownership_context(tmp_path)
    malformed_source = _sort_source().replace(
        "    mnDiagram_Assets* assets = (mnDiagram_Assets*) &mnDiagram_804A0750;\n    u8* dst = assets->sorted_names;",
        "    u8* dst = mnDiagram_804A076C.sorted_names;",
    )

    candidates = generate_source_family_candidates(
        malformed_source,
        context,
        max_per_dimension=10,
        include_source=True,
    )
    assert candidates == []

    payload = build_generated_source_family_payload(candidates, context)

    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["generation_blockers"][0]["reason"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_SOURCE_REGION_PATTERN_BLOCKER
    )
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"]
        == synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
    )
    assert dimension["status"] == "blocked"
    assert payload["terminal_summary"]
    assert payload["source_model_proof"]["source_family_synthesis"]
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )


def test_normalize_meta_ceiling_prefers_post_cross_tu_terminal_proof(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)

    assert context.current_ceiling["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert context.next_unsupported_source_family == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert context.current_ceiling["source_family_synthesis"]["retained_scored_probes"]


def test_sort_post_cross_tu_terminal_context_generates_no_old_probes(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates == []


def test_sort_cross_tu_no_modeled_ceiling_suppresses_candidate_generation(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_model_only_context(tmp_path)

    assert context.next_unsupported_source_model == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert context.next_unsupported_source_family == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert context.current_ceiling["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates == []


def test_sort_cross_tu_protected_target_rows_suppress_candidate_generation(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_protected_targets_only_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates == []


def test_sort_cross_tu_no_modeled_source_model_terminalizes_with_retained_split_evidence(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_model_only_context(tmp_path)

    payload = build_generated_source_family_payload([], context)

    assert payload["status"] == "terminal"
    assert payload["kind"] == synthesis.PROOF_KIND
    assert payload["terminal_summary"]["kind"] == "no-post-ceiling-sort-source-family"
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload.get("reason") != "score-rows-not-terminal-safe"
    blocker_reasons = {
        value
        for row in payload["terminal_blockers"]
        for value in (row["reason"], row["terminal_blocker"])
    }
    assert synthesis.SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER in (
        blocker_reasons
    )
    retained = payload["source_model_proof"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    assert {"post-cross-tu-ig34-retained", "post-cross-tu-ig44-retained"} <= {
        row["candidate_id"] for row in retained
    }
    for row in retained:
        assert row["source_hunks"]
        assert row["source_retained"]
        assert row["pcdump_path"]
        assert row["target_score"]
        assert row["structural_guard"]


def test_sort_cross_tu_no_modeled_source_family_continuation_terminalizes(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_model_only_context(tmp_path)
    rows = [
        dict(row)
        for row in context.current_ceiling["source_family_synthesis"][
            "retained_scored_probes"
        ]
    ]
    classified = {
        "function": SORT_FUNCTION,
        "source_function": SORT_SOURCE_FUNCTION,
        "status": "blocked",
        "reason": "score-rows-not-terminal-safe",
        "candidate_count": len(rows),
        "score_count": len(rows),
        "joined_score_count": len(rows),
        "score_rows": rows,
        "context": context.to_dict(),
        "source_model_proof": {
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "retained_scored_probes": rows,
                "candidate_scores": rows,
                "next_unsupported_source_model": (
                    synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
                ),
            }
        },
    }

    payload = build_source_family_continuation_payload(classified, [])

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["terminal_reason"] == (
        "post-meta-gpr-one-hit-source-family-continuation-exhausted/"
        "protected-structural-ceiling"
    )
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["continuation"] is None
    assert synthesis.SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER in (
        payload["terminal_blockers"]
    )
    assert "post-meta-source-family-continuation-needs-more-evidence" not in (
        payload["terminal_blockers"]
    )
    retained = payload["source_model_proof"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    assert {"post-cross-tu-ig34-retained", "post-cross-tu-ig44-retained"} <= {
        row["candidate_id"] for row in retained
    }
    for row in retained:
        assert row["source_hunks"]
        assert row["source_retained"]
        assert row["pcdump_path"]
        assert row["target_score"]
        assert row["structural_guard"]


def test_sort_post_cross_tu_continuation_generates_only_new_dimension(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)

    default_candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert default_candidates == []
    assert 2 <= len(candidates) <= 4
    assert {row["dimension_id"] for row in candidates} == {
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION
    }
    assert not {row["dimension_id"] for row in candidates} & (
        OLD_SORT_DIMENSIONS | NATURAL_SORT_DIMENSIONS | SEMANTIC_SORT_DIMENSIONS
    )
    assert len({row["candidate_id"] for row in candidates}) == len(candidates)
    component_ids = {
        component["component_id"]
        for row in candidates
        for component in row["source_components"]
    }
    assert {
        "sort-post-cross-tu-stable-selected-candidate-names",
        "sort-post-cross-tu-local-destination-owner",
        "sort-post-cross-tu-text-total-cache",
        "sort-post-cross-tu-emission-cursor-owner",
    } <= component_ids


def test_sort_post_cross_tu_hypotheses_require_full_unit_and_joint_assignments(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert candidates
    for row in candidates:
        metadata = row["validation_metadata"]
        assert row["source_hunks"]
        assert row["source_components"]
        assert metadata["requires_full_unit_source"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["required_preserved_assignments"] == [
            "IG34->r27",
            "IG44->r25",
        ]
        assert metadata["score_function"] == SORT_SOURCE_FUNCTION
        assert metadata["source_components"]
        assert "--full-unit-source" in metadata["score_source_command_hint"]
        assert "--checkdiff-guard" in metadata["score_source_command_hint"]


def test_sort_post_cross_tu_opt_in_zero_candidates_emit_new_terminal_proof(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)

    payload = build_generated_source_family_payload(
        [],
        context,
        continue_after_final_source_family=True,
    )

    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["scored_count"] == 2
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_MODEL
    )
    assert payload["generation_blockers"][0]["reason"] == (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_SOURCE_REGION_PATTERN_BLOCKER
    )
    assert payload["retained_scored_probes"]
    assert payload["source_model_proof"]["retained_scored_probes"]
    blocker_reasons = {
        value
        for row in payload["terminal_blockers"]
        for value in (row["reason"], row["terminal_blocker"])
    }
    assert (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_SOURCE_REGION_PATTERN_BLOCKER
        in blocker_reasons
    )


def test_sort_post_cross_tu_hypothesis_classifier_requires_joint_targets(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
        continue_after_final_source_family=True,
    )
    candidate = {
        **candidates[0],
        "candidate_path": "/tmp/post-cross-tu-source-hypothesis.c",
    }

    ig34_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=22, accepted=True)],
        context,
        continue_after_final_source_family=True,
    )
    assert ig34_only["status"] == "terminal"
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in ig34_only["terminal_blockers"]
    )
    assert ig34_only["next_unsupported_source_family"] == (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )

    ig44_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=24, actual44=25, accepted=True)],
        context,
        continue_after_final_source_family=True,
    )
    assert ig44_only["status"] == "terminal"
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in ig44_only["terminal_blockers"]
    )
    assert (
        "required-assignment-not-preserved:IG34->r27"
        in ig44_only["score_rows"][0]["blockers"]
    )

    joint_score = _score(candidate, actual34=27, actual44=25, accepted=True)
    joint_score["pcdump_path"] = "/tmp/post-cross-tu-source-hypothesis.pcdump.txt"
    actionable = classify_source_family_scores(
        [candidate],
        [joint_score],
        context,
        continue_after_final_source_family=True,
    )
    assert actionable["status"] == "actionable"
    best = actionable["ranked_candidates"][0]
    assert best["candidate_id"] == candidate["candidate_id"]
    assert best["source_retained"] == candidate["candidate_path"]
    assert best["pcdump_path"] == "/tmp/post-cross-tu-source-hypothesis.pcdump.txt"
    assert best["target_score"]
    assert best["source_hunks"]


def test_sort_post_cross_tu_zero_candidates_emit_terminal_proof_with_real_evidence(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_context(tmp_path)

    payload = build_generated_source_family_payload([], context)

    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["scored_count"] == 2
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["candidate_scores"]
    assert payload["retained_scored_probes"]
    assert payload["source_hunks_by_candidate"]
    retained = payload["retained_scored_probes"][0]
    assert retained["source_retained"]
    assert retained["pcdump_path"]
    assert retained["target_score"]["virtuals"]
    assert retained["structural_guard"]
    blocker_reasons = {
        value
        for row in payload["terminal_blockers"]
        for value in (row["reason"], row["terminal_blocker"])
    }
    assert synthesis.SORT_CROSS_TU_NO_MODELED_SOURCE_TERMINAL_BLOCKER in (
        blocker_reasons
    )
    assert synthesis.SORT_CROSS_TU_ONE_HIT_TERMINAL_BLOCKER in blocker_reasons
    assert payload["generation_blockers"][0]["reason"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )

    proof = payload["source_model_proof"]
    proof_synthesis = proof["source_family_synthesis"]
    assert proof["candidate_scores"] == payload["candidate_scores"]
    assert proof["retained_scored_probes"] == payload["retained_scored_probes"]
    assert proof["source_hunks_by_candidate"] == payload["source_hunks_by_candidate"]
    assert proof["scored_count"] == payload["scored_count"]
    assert proof_synthesis["candidate_scores"] == payload["candidate_scores"]
    assert (
        proof_synthesis["retained_scored_probes"] == (payload["retained_scored_probes"])
    )
    assert (
        proof_synthesis["source_hunks_by_candidate"]
        == (payload["source_hunks_by_candidate"])
    )
    assert proof_synthesis["scored_count"] == payload["scored_count"]
    assert (
        proof_synthesis["one_hit_summary"]["protected_targets_not_jointly_preserved"]
        is True
    )
    assert not [
        row
        for row in payload.get("candidates", [])
        if row.get("dimension_id") in OLD_SORT_DIMENSIONS
    ]


def _sort_post_cross_tu_selection_swap_terminal_payload(tmp_path: Path) -> dict:
    context = _sort_post_cross_tu_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    return classify_source_family_scores(
        candidates,
        [
            _score(
                candidate,
                actual34=5,
                actual44=(
                    25
                    if candidate["candidate_id"].endswith("paired-text-total-cache")
                    else 26
                ),
                accepted=False,
            )
            for candidate in candidates
        ],
        context,
        continue_after_final_source_family=True,
    )


def _sort_post_cross_tu_broader_natural_rewrite_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_post_cross_tu_selection_swap_terminal_payload(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def test_sort_post_cross_tu_final_continuation_generates_broader_natural_rewrites(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_broader_natural_rewrite_context(tmp_path)

    default_candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert default_candidates
    assert {row["dimension_id"] for row in default_candidates} == {
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
    }
    assert candidates
    assert {row["dimension_id"] for row in candidates} == {
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
    }
    assert not {row["dimension_id"] for row in candidates} & (
        OLD_SORT_DIMENSIONS | NATURAL_SORT_DIMENSIONS | SEMANTIC_SORT_DIMENSIONS
    )
    assert any(
        row["validation_metadata"].get("seed_candidate_id", "").endswith(
            "paired-text-total-cache"
        )
        for row in candidates
    )
    for row in candidates:
        metadata = row["validation_metadata"]
        assert row["source_hunks"]
        assert row["source_components"]
        assert metadata["requires_full_unit_source"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["required_preserved_assignments"] == [
            "IG34->r27",
            "IG44->r25",
        ]
        assert metadata["post_cross_tu_broader_natural_rewrite"] is True
        assert metadata["seed_target_score"]["matched"] == 1
        assert "--full-unit-source" in metadata["score_source_command_hint"]
        assert "--checkdiff-guard" in metadata["score_source_command_hint"]


def test_sort_post_cross_tu_selection_swap_default_zero_candidates_terminalize_broader_natural(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_broader_natural_rewrite_context(tmp_path)

    payload = build_generated_source_family_payload([], context)

    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_MODEL
    )
    assert payload["generation_blockers"][0]["reason"] == (
        synthesis.SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_SOURCE_REGION_PATTERN_BLOCKER
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert proof_synthesis["retained_scored_probes"]
    assert proof_synthesis["source_hunks_by_candidate"]


def test_sort_post_cross_tu_broader_natural_rewrite_classifies_seed_loss_and_joint_hit(
    tmp_path: Path,
) -> None:
    context = _sort_post_cross_tu_broader_natural_rewrite_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )
    candidate = {
        **candidates[0],
        "candidate_path": "/tmp/post-cross-tu-broader-natural.c",
    }

    ig44_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=5, actual44=25, accepted=False)],
        context,
        continue_after_final_source_family=True,
    )

    assert ig44_only["status"] == "terminal"
    assert ig44_only["terminal_reason"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_TERMINAL_REASON
    )
    assert ig44_only["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
    )
    assert ig44_only["retained_scored_probes"]
    retained = ig44_only["retained_scored_probes"][0]
    assert retained["target_score"]["matched"] == 1
    assert retained["source_hunks"]
    assert retained["structural_guard"]
    assert any(
        row["reason"] == "protected-targets-not-jointly-preserved"
        for row in ig44_only["terminal_blockers"]
    )

    joint_score = _score(candidate, actual34=27, actual44=25, accepted=True)
    joint_score["pcdump_path"] = "/tmp/post-cross-tu-broader-natural.pcdump.txt"
    actionable = classify_source_family_scores(
        [candidate],
        [joint_score],
        context,
        continue_after_final_source_family=True,
    )

    assert actionable["status"] == "actionable"
    best = actionable["ranked_candidates"][0]
    assert best["target_score"]["matched"] == 2
    assert best["source_retained"] == candidate["candidate_path"]
    assert best["pcdump_path"] == "/tmp/post-cross-tu-broader-natural.pcdump.txt"


def _sort_post_broader_natural_inline_boundary_terminal_payload(
    tmp_path: Path,
) -> dict:
    context = _sort_post_cross_tu_broader_natural_rewrite_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )
    scored = []
    probe_dir = tmp_path / "post_inline_seed_probes"
    probe_dir.mkdir(exist_ok=True)
    for candidate in candidates:
        candidate_path = probe_dir / f"{candidate['candidate_id']}.c"
        candidate_path.write_text(candidate.get("source_text", ""), encoding="utf-8")
        candidate["candidate_path"] = str(candidate_path)
        is_nested = candidate["candidate_id"].endswith("nested-text-total-decision")
        score = _score(
            candidate,
            actual34=5,
            actual44=25 if is_nested else 26,
            accepted=False,
        )
        score["pcdump_path"] = f"/tmp/{candidate['candidate_id']}.pcdump.txt"
        score["structural_guard"]["classification_primary"] = (
            "inline-boundary-toolchain-artifact"
        )
        score["structural_guard"]["normalized_diff_lines"] = 22 if is_nested else 28
        scored.append(score)
    return classify_source_family_scores(
        candidates,
        scored,
        context,
        continue_after_final_source_family=True,
    )


def _sort_post_broader_natural_inline_boundary_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_post_broader_natural_inline_boundary_terminal_payload(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def _sort_broader_terminal_retained_aggregate_with_stale_terminal_frontier(
    tmp_path: Path,
) -> dict:
    broader_terminal = _sort_post_broader_natural_inline_boundary_terminal_payload(
        tmp_path
    )
    broader_proof = json.loads(json.dumps(broader_terminal["source_model_proof"]))
    broader_proof["terminal_reason"] = broader_terminal["terminal_reason"]

    stale_proof = json.loads(json.dumps(broader_proof))
    stale_proof["next_unsupported_source_family"] = (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )
    stale_proof["next_unsupported_source_model"] = (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_MODEL
    )
    stale_proof["terminal_reason"] = (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_TERMINAL_REASON
    )
    stale_proof["attempted_equivalence_classes"] = [
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION,
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION,
    ]
    stale_synthesis = stale_proof["source_family_synthesis"]
    stale_synthesis["next_unsupported_source_family"] = (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )
    stale_synthesis["next_unsupported_source_model"] = (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_MODEL
    )
    stale_synthesis["terminal_reason"] = (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_TERMINAL_REASON
    )
    stale_synthesis["attempted_equivalence_classes"] = [
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION,
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION,
    ]
    stale_synthesis["exhausted_dimensions"] = [
        {
            "dimension_id": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
            ),
            "status": "scored-terminal",
            "candidate_ids": [
                "post-meta-sort-post-inline-boundary-selection-emission-stale"
            ],
        }
    ]

    stale_frontier = {
        "function": SORT_FUNCTION,
        "frontier_id": f"{SORT_FUNCTION}|source-model-proof|stale-post-inline",
        "family_id": "post_meta_ceiling_sort_source_family_synthesis",
        "status": "terminal",
        "terminal": True,
        "terminal_reason": stale_proof["terminal_reason"],
        "source_model_proof": stale_proof,
    }
    return {
        "status": "all-known-frontiers-exhausted",
        "artifact_count": 1,
        "parsed_artifact_count": 1,
        "skipped_artifacts": [],
        "functions": [
            {
                "function": SORT_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [stale_frontier],
                "next_frontier": None,
                "meta_ceiling": {
                    "status": "terminal-current-source-shape-ceiling",
                    "terminal_proof": broader_proof,
                    "closed_families": [
                        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
                    ],
                },
                "summary": {
                    "unexhausted_count": 0,
                    "terminal_count": 1,
                    "suppressed_by_terminal_count": 0,
                },
            }
        ],
        "next_frontier": None,
    }


def _sort_post_inline_boundary_selection_emission_terminal_payload(
    tmp_path: Path,
) -> dict:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )
    seed_dir = tmp_path / "post_inline_seed_probes"
    seed_dir.mkdir(exist_ok=True)
    scored = []
    for candidate in candidates:
        source_path = seed_dir / f"{candidate['candidate_id']}.c"
        source_path.write_text(str(candidate.get("source_text") or ""))
        candidate["candidate_path"] = str(source_path)
        is_best = candidate["candidate_id"].endswith("decision-return-local")
        score = _score(
            candidate,
            actual34=4 if is_best else 23,
            actual44=25 if is_best else 26,
            accepted=False,
        )
        score["pcdump_path"] = f"/tmp/{candidate['candidate_id']}.pcdump.txt"
        score["structural_guard"]["classification_primary"] = (
            "inline-boundary-toolchain-artifact"
        )
        score["structural_guard"]["normalized_diff_lines"] = 33 if is_best else 28
        scored.append(score)
    return classify_source_family_scores(
        candidates,
        scored,
        context,
        continue_after_final_source_family=True,
    )


def _sort_post_inline_boundary_selection_emission_context(tmp_path: Path):
    return normalize_meta_ceiling_context(
        [_sort_post_inline_boundary_selection_emission_terminal_payload(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )


def test_sort_post_broader_natural_terminal_context_generates_no_old_probes(
    tmp_path: Path,
) -> None:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates == []


def test_sort_post_broader_natural_continuation_generates_only_inline_boundary_dimension(
    tmp_path: Path,
) -> None:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert candidates
    assert {row["dimension_id"] for row in candidates} == {
        SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
    }
    assert not {row["dimension_id"] for row in candidates} & (
        OLD_SORT_DIMENSIONS
        | NATURAL_SORT_DIMENSIONS
        | SEMANTIC_SORT_DIMENSIONS
        | {
            synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_DIMENSION,
            SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION,
        }
    )


def test_sort_retained_aggregate_prefers_broader_terminal_over_stale_attempted_dimension(
    tmp_path: Path,
) -> None:
    context = normalize_meta_ceiling_context(
        [_sort_broader_terminal_retained_aggregate_with_stale_terminal_frontier(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    assert context.next_unsupported_source_family == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
    )
    assert context.next_unsupported_source_family != (
        synthesis.SORT_POST_CROSS_TU_SELECTION_SWAP_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )


def test_sort_retained_aggregate_continuation_generates_post_broader_not_broader_again(
    tmp_path: Path,
) -> None:
    context = normalize_meta_ceiling_context(
        [_sort_broader_terminal_retained_aggregate_with_stale_terminal_frontier(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert {row["dimension_id"] for row in candidates} == {
        SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
    }
    assert {row["candidate_id"] for row in candidates} == {
        "post-meta-sort-post-broader-natural-inline-boundary-nested-decision-helper",
        "post-meta-sort-post-broader-natural-inline-boundary-helper-local-text-total",
        "post-meta-sort-post-broader-natural-inline-boundary-preloaded-text-helper",
        "post-meta-sort-post-broader-natural-inline-boundary-decision-return-local",
        "post-meta-sort-post-broader-natural-inline-boundary-helper-dst-emission-owner",
    }
    assert not any(
        row["dimension_id"] == SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_DIMENSION
        for row in candidates
    )


def test_sort_retained_aggregate_without_continuation_does_not_repeat_broader_natural(
    tmp_path: Path,
) -> None:
    context = normalize_meta_ceiling_context(
        [_sort_broader_terminal_retained_aggregate_with_stale_terminal_frontier(tmp_path)],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    payload = build_generated_source_family_payload(candidates, context)

    assert candidates == []
    assert payload["candidate_count"] == 0
    assert payload["context"]["next_unsupported_source_family"] == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
    )
    assert context.next_unsupported_source_family == (
        SORT_POST_CROSS_TU_BROADER_NATURAL_REWRITE_FINAL_FAMILY
    )


def test_sort_mixed_stage_terminal_frontier_rank_is_capped_by_direct_next_family(
    tmp_path: Path,
) -> None:
    aggregate = _sort_broader_terminal_retained_aggregate_with_stale_terminal_frontier(
        tmp_path
    )
    function = aggregate["functions"][0]
    broader = function["meta_ceiling"]["terminal_proof"]
    stale = function["terminal_frontiers"][0]["source_model_proof"]
    dimension_only = json.loads(json.dumps(stale))
    dimension_only.pop("next_unsupported_source_family", None)
    dimension_only.pop("next_unsupported_source_model", None)
    dimension_only.pop("terminal_reason", None)
    for key in (
        "next_unsupported_source_family",
        "next_unsupported_source_model",
        "terminal_reason",
    ):
        dimension_only["source_family_synthesis"].pop(key, None)

    assert synthesis._meta_ceiling_source_model_stage_rank(broader, 0) > (
        synthesis._meta_ceiling_source_model_stage_rank(stale, 1)
    )
    assert synthesis._meta_ceiling_source_model_stage_rank(dimension_only, 2) > (
        synthesis._meta_ceiling_source_model_stage_rank(broader, 0)
    )


def test_sort_post_broader_natural_requires_complete_terminal_marker(
    tmp_path: Path,
) -> None:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)

    def strip_next_model(value):
        if isinstance(value, dict):
            return {
                key: strip_next_model(item)
                for key, item in value.items()
                if key != "next_unsupported_source_model"
            }
        if isinstance(value, list):
            return [strip_next_model(item) for item in value]
        return value

    malformed_context = replace(
        context,
        current_ceiling=strip_next_model(context.current_ceiling),
        next_unsupported_source_model=None,
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        malformed_context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert not any(
        row["dimension_id"]
        == SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_DIMENSION
        for row in candidates
    )


def test_sort_post_broader_natural_inline_boundary_candidates_require_seed_and_full_unit_scoring(
    tmp_path: Path,
) -> None:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert candidates
    assert len(candidates) <= 5
    for row in candidates:
        metadata = row["validation_metadata"]
        assert row["source_hunks"]
        assert row["source_components"]
        assert metadata["post_broader_natural_inline_boundary_source_hypothesis"] is True
        assert metadata["requires_full_unit_source"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["score_function"] == SORT_SOURCE_FUNCTION
        assert metadata["required_preserved_assignments"] == [
            "IG34->r27",
            "IG44->r25",
        ]
        assert metadata["seed_candidate_id"].endswith("nested-text-total-decision")
        assert metadata["seed_source_retained"]
        assert metadata["seed_pcdump_path"]
        assert metadata["seed_structural_guard"]["classification_primary"] == (
            "inline-boundary-toolchain-artifact"
        )
        assert "--full-unit-source" in metadata["score_source_command_hint"]
        assert "--checkdiff-guard" in metadata["score_source_command_hint"]


def test_sort_post_broader_natural_inline_boundary_classifier_requires_joint_targets(
    tmp_path: Path,
) -> None:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
        continue_after_final_source_family=True,
    )
    candidate = {
        **candidates[0],
        "candidate_path": "/tmp/post-broader-inline-boundary.c",
    }

    ig34_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=27, actual44=22, accepted=True)],
        context,
        continue_after_final_source_family=True,
    )
    assert ig34_only["status"] == "terminal"
    assert ig34_only["terminal_reason"] == (
        SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_TERMINAL_REASON
    )

    ig44_only = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=24, actual44=25, accepted=True)],
        context,
        continue_after_final_source_family=True,
    )
    assert ig44_only["status"] == "terminal"
    assert ig44_only["next_unsupported_source_family"] == (
        SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )
    assert (
        "required-assignment-not-preserved:IG34->r27"
        in ig44_only["score_rows"][0]["blockers"]
    )

    joint_score = _score(candidate, actual34=27, actual44=25, accepted=True)
    joint_score["pcdump_path"] = "/tmp/post-broader-inline-boundary.pcdump.txt"
    actionable = classify_source_family_scores(
        [candidate],
        [joint_score],
        context,
        continue_after_final_source_family=True,
    )
    assert actionable["status"] == "actionable"
    best = actionable["ranked_candidates"][0]
    assert best["candidate_id"] == candidate["candidate_id"]
    assert best["source_retained"] == candidate["candidate_path"]
    assert best["pcdump_path"] == "/tmp/post-broader-inline-boundary.pcdump.txt"
    assert best["target_score"]
    assert best["source_hunks"]


def test_sort_post_broader_natural_inline_boundary_zero_candidates_terminalize_with_seed_evidence(
    tmp_path: Path,
) -> None:
    context = _sort_post_broader_natural_inline_boundary_context(tmp_path)

    payload = build_generated_source_family_payload(
        [],
        context,
        continue_after_final_source_family=True,
    )

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_family"] == (
        SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_FINAL_FAMILY
    )
    assert payload["generation_blockers"][0]["reason"] == (
        synthesis.SORT_POST_BROADER_NATURAL_INLINE_BOUNDARY_SOURCE_HYPOTHESIS_SOURCE_REGION_PATTERN_BLOCKER
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert proof_synthesis["retained_scored_probes"]
    assert proof_synthesis["source_hunks_by_candidate"]
    blocker = payload["generation_blockers"][0]
    assert blocker["seed_candidate_id"].endswith("nested-text-total-decision")
    assert blocker["seed_source_hunks"]


def test_sort_post_inline_boundary_terminal_context_generates_no_old_probes(
    tmp_path: Path,
) -> None:
    context = _sort_post_inline_boundary_selection_emission_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )

    assert candidates == []


def test_sort_post_inline_final_context_zero_generation_terminalizes(
    tmp_path: Path,
) -> None:
    base_context = _sort_post_inline_boundary_selection_emission_context(tmp_path)
    final_model = (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
    )
    context = replace(
        base_context,
        next_unsupported_source_model=final_model,
        next_unsupported_source_family=(
            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
        ),
        current_ceiling={
            **base_context.current_ceiling,
            "next_unsupported_source_model": final_model,
            "next_unsupported_source_family": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
            ),
        },
    )

    payload = build_generated_source_family_payload(
        [],
        context,
        continue_after_final_source_family=True,
    )

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == final_model
    assert payload["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert payload["candidate_count"] == 0

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        continue_after_final_source_family=True,
    )
    assert candidates == []


def test_sort_post_inline_final_terminal_group_prevents_stale_generation(
    tmp_path: Path,
) -> None:
    stale_model = (
        "Post-meta Sort one-hit continuation exhausted bounded structural "
        "repair plus bounded semantic IG34/IG44 one-hit recombination/protected "
        "continuation of source-family hits; the next unsupported model is a "
        "broader natural C sort rewrite outside these retained source families."
    )
    payload = {
        "function": SORT_FUNCTION,
        "retained_frontiers_meta_ceiling": {
            "terminal_proof": {
                "terminal_reason": (
                    "post-meta-gpr-one-hit-source-family-continuation-exhausted/protected-structural-ceiling"
                ),
                "next_unsupported_source_model": stale_model,
            },
            "terminal_groups": [
                {
                    "terminal_reason": (
                        "post-meta-gpr-one-hit-source-family-continuation-exhausted/protected-structural-ceiling"
                    ),
                    "next_unsupported_source_model": stale_model,
                },
                {
                    "terminal_reason": (
                        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
                    ),
                    "next_unsupported_source_model": (
                        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
                    ),
                    "next_unsupported_source_family": (
                        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
                    ),
                    "exhausted_dimensions": [
                        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
                    ],
                },
            ],
        },
    }
    context = normalize_meta_ceiling_context(
        [payload],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    assert context.next_unsupported_source_family == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        continue_after_final_source_family=True,
    )
    terminal = build_generated_source_family_payload(
        candidates,
        context,
        continue_after_final_source_family=True,
    )

    assert candidates == []
    assert terminal["status"] == "terminal"
    assert terminal["candidate_count"] == 0
    assert terminal["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert "broader natural C sort rewrite" not in json.dumps(terminal)


def test_sort_post_inline_final_family_promotes_stale_next_model(
    tmp_path: Path,
) -> None:
    stale_model = (
        "Post-meta Sort one-hit continuation exhausted bounded structural "
        "repair; the next unsupported model is a broader natural C sort rewrite "
        "outside these retained source families."
    )
    payload = {
        "function": SORT_FUNCTION,
        "current_ceiling": {
            "terminal_reason": (
                "post-meta-gpr-one-hit-source-family-continuation-exhausted/protected-structural-ceiling"
            ),
            "next_unsupported_source_model": stale_model,
            "next_unsupported_source_family": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
            ),
            "source_family_synthesis": {
                "next_unsupported_source_model": stale_model,
            },
        },
    }
    context = normalize_meta_ceiling_context(
        [payload],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    assert context.next_unsupported_source_model == (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
    )
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        continue_after_final_source_family=True,
    )
    terminal = build_generated_source_family_payload(
        candidates,
        context,
        continue_after_final_source_family=True,
    )

    assert candidates == []
    assert terminal["status"] == "terminal"
    assert "broader natural C sort rewrite" not in json.dumps(terminal)


def test_sort_post_inline_boundary_continuation_generates_selection_emission_only(
    tmp_path: Path,
) -> None:
    context = _sort_post_inline_boundary_selection_emission_context(tmp_path)

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
        continue_after_final_source_family=True,
    )

    assert candidates
    assert {row["dimension_id"] for row in candidates} == {
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
    }
    assert {row["variant_id"] for row in candidates} == {
        "helper-selected-name-carried",
        "helper-selected-total-carried",
        "helper-emission-cursor-owner",
        "helper-selected-state-emission-coupled",
    }
    assert all(
        row["candidate_id"].startswith(
            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_PREFIX
        )
        for row in candidates
    )
    assert not any(
        row["candidate_id"].startswith(
            "post-meta-sort-post-broader-natural-inline-boundary-"
        )
        for row in candidates
    )
    assert any(
        row["validation_metadata"]["seed_candidate_id"].endswith(
            "decision-return-local"
        )
        and row["validation_metadata"]["seed_structural_guard"][
            "normalized_diff_lines"
        ]
        == 33
        for row in candidates
    )
    for row in candidates:
        source_text = row["source_text"]
        assert source_text.count("{") == source_text.count("}")
        assert "\n        }\n        }\n        if (max_idx != i) {" not in source_text
        metadata = row["validation_metadata"]
        assert metadata["requires_full_unit_source"] is True
        assert metadata["requires_structural_guard"] is True
        assert metadata["requires_target_score_validation"] is True
        assert metadata["post_inline_boundary_selection_emission_source_shape"] is True
        assert metadata["required_preserved_assignments"] == [
            "IG34->r27",
            "IG44->r25",
        ]
        assert "--full-unit-source" in metadata["score_source_command_hint"]
        assert "--checkdiff-guard" in metadata["score_source_command_hint"]

    written = write_source_family_candidates(
        candidates,
        tmp_path / "post-inline-selection-emission-probes",
        include_source=True,
    )
    for row in written:
        path = Path(row["source_retained"])
        source_text = path.read_text(encoding="utf-8")
        assert path.exists()
        assert source_text.count("{") == source_text.count("}")
        assert "\n        }\n        }\n        if (max_idx != i) {" not in source_text
        assert row["source_valid"] is True
        assert row["source_validation"]["status"] == "valid"
        assert SORT_SOURCE_FUNCTION in source_text


def test_sort_post_inline_boundary_invalid_generated_source_blocks_before_score(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = _sort_post_inline_boundary_selection_emission_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
        continue_after_final_source_family=True,
    )
    assert candidates
    candidates[0]["source_text"] = (
        candidates[0]["source_text"]
        + "\n        }\n        }\n        if (max_idx != i) {\n"
    )
    written = write_source_family_candidates(
        candidates,
        tmp_path / "invalid-post-inline-selection-emission-probes",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid generated source should not invoke score-source")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    score_rows = score_source_candidates(
        written,
        repo_root=tmp_path,
        context=context,
        target=tmp_path / "target.json",
        cflags_from=Path("src/melee/mn/mndiagram.c"),
        expression_source=tmp_path / "source.c",
    )
    payload = classify_source_family_scores(
        written,
        score_rows,
        context,
        continue_after_final_source_family=True,
    )

    assert payload["status"] == "blocked"
    assert payload["reason"] == "invalid-generated-source"
    assert payload.get("terminal_summary") is None
    assert payload.get("next_unsupported_source_family") is None
    assert score_rows[0]["error"] == "invalid-source"
    assert score_rows[0]["source_validation"]["status"] == "invalid-source"
    assert score_rows[0]["source_validation"]["brace_balance"] == -1
    assert payload["score_rows"][0]["score_error"] == "invalid-source"
    assert payload["score_rows"][0]["source_validation"]["brace_balance"] == -1
    assert any(
        row["reason"] == "invalid-generated-source"
        for row in payload["blockers"]
    )


def test_sort_post_inline_boundary_selection_emission_classifier_sets_final_family(
    tmp_path: Path,
) -> None:
    context = _sort_post_inline_boundary_selection_emission_context(tmp_path)
    candidate = {
        "candidate_id": (
            f"{SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_PREFIX}"
            "helper-selected-name-carried"
        ),
        "candidate_path": "/tmp/post-inline-selection-emission.c",
        "dimension_id": (
            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        ),
        "equivalence_class": (
            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        ),
        "variant_id": "helper-selected-name-carried",
        "strategy": "helper-selected-name-carried",
        "rationale": "test post-inline-boundary selected-name carry",
        "expected_effect": "tests selected-name lifetime after helper exhaustion",
        "source_hunks": [{"hunk_id": "post-inline-h001"}],
        "source_components": [
            {"component_id": "sort-post-inline-boundary-selected-name-carry"}
        ],
        "validation_metadata": {
            "dimension_id": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
            ),
            "post_inline_boundary_selection_emission_source_shape": True,
            "requires_full_unit_source": True,
            "requires_structural_guard": True,
            "required_preserved_assignments": ["IG34->r27", "IG44->r25"],
        },
    }

    terminal = classify_source_family_scores(
        [candidate],
        [_score(candidate, actual34=4, actual44=25, accepted=False)],
        context,
        continue_after_final_source_family=True,
    )

    assert terminal["status"] == "terminal"
    assert terminal["terminal_reason"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert terminal["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert terminal["exhausted_dimensions"] == [
        {
            "dimension_id": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
            ),
            "status": "scored-terminal",
            "exhaustion_reason": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
            ),
            "candidate_ids": [candidate["candidate_id"]],
        }
    ]


def test_sort_post_inline_fallback_structural_rejections_terminalize(
    tmp_path: Path,
) -> None:
    base_context = _sort_post_inline_boundary_selection_emission_context(tmp_path)
    final_model = (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
    )
    context = replace(
        base_context,
        next_unsupported_source_model=final_model,
        next_unsupported_source_family=(
            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
        ),
        current_ceiling={
            **base_context.current_ceiling,
            "next_unsupported_source_model": final_model,
            "next_unsupported_source_family": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
            ),
        },
    )
    candidates = [
        {
            "candidate_id": "post-meta-source-family-sort-init-indexed-write-name-total-locals",
            "candidate_path": "/tmp/post-inline-fallback-init.c",
            "dimension_id": "sort-init-indexed-write",
            "source_hunks": [{"hunk_id": "fallback-init-h001"}],
            "source_components": [{"component_id": "sort-init-indexed-write"}],
        },
        {
            "candidate_id": "post-meta-source-family-sort-swap-slot-lvalue-direct-assets",
            "candidate_path": "/tmp/post-inline-fallback-swap.c",
            "dimension_id": "sort-swap-slot-lvalue",
            "source_hunks": [{"hunk_id": "fallback-swap-h001"}],
            "source_components": [{"component_id": "sort-swap-slot-lvalue"}],
        },
    ]
    scores = []
    for candidate in candidates:
        score = _score(candidate, actual34=4, actual44=23, accepted=False)
        score["pcdump_path"] = f"/tmp/{candidate['candidate_id']}.pcdump.txt"
        score["structural_guard"]["classification_primary"] = (
            "inline-boundary-toolchain-artifact"
        )
        score["structural_guard"]["normalized_diff_lines"] = 28
        scores.append(score)

    terminal = classify_source_family_scores(
        candidates,
        scores,
        context,
        continue_after_final_source_family=True,
    )

    assert terminal["status"] == "terminal"
    assert terminal["terminal_reason"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert terminal["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    exhausted_dimensions = {
        row["dimension_id"] for row in terminal["exhausted_dimensions"]
    }
    assert (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
        in exhausted_dimensions
    )
    synthesis_payload = terminal["source_model_proof"]["source_family_synthesis"]
    retained = synthesis_payload["retained_scored_probes"]
    assert {row["candidate_id"] for row in retained} == {
        row["candidate_id"] for row in candidates
    }
    assert all(row["target_score"]["matched"] == 0 for row in retained)
    assert all(row["source_retained"] for row in retained)
    assert all(row["pcdump_path"] for row in retained)
    assert any(
        row["reason"] == "structural-guard-not-accepted"
        for row in terminal["terminal_blockers"]
    )


def test_source_family_continuation_preserves_sort_post_inline_fallback_final_family(
    tmp_path: Path,
) -> None:
    base_context = _sort_post_inline_boundary_selection_emission_context(tmp_path)
    final_model = (
        synthesis.SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_MODEL
    )
    context = replace(
        base_context,
        next_unsupported_source_model=final_model,
        next_unsupported_source_family=(
            SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
        ),
        current_ceiling={
            **base_context.current_ceiling,
            "next_unsupported_source_model": final_model,
            "next_unsupported_source_family": (
                SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
            ),
        },
    )
    candidates = [
        {
            "candidate_id": "post-meta-source-family-sort-init-indexed-write-name-total-locals",
            "candidate_path": "/tmp/post-inline-fallback-init.c",
            "dimension_id": "sort-init-indexed-write",
            "source_hunks": [{"hunk_id": "fallback-init-h001"}],
            "source_components": [{"component_id": "sort-init-indexed-write"}],
        },
        {
            "candidate_id": "post-meta-source-family-sort-swap-slot-lvalue-direct-assets",
            "candidate_path": "/tmp/post-inline-fallback-swap.c",
            "dimension_id": "sort-swap-slot-lvalue",
            "source_hunks": [{"hunk_id": "fallback-swap-h001"}],
            "source_components": [{"component_id": "sort-swap-slot-lvalue"}],
        },
    ]
    scores = [
        _score(candidate, actual34=4, actual44=23, accepted=False)
        for candidate in candidates
    ]
    terminal = classify_source_family_scores(
        candidates,
        scores,
        context,
        continue_after_final_source_family=True,
    )

    payload = build_source_family_continuation_payload(terminal, [])

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_model"] == final_model
    assert payload["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert "broader natural C sort rewrite" not in (
        payload["next_unsupported_source_model"]
    )
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    assert proof_synthesis["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_sort_legacy_fallback_rejections_without_post_inline_context_do_not_use_post_inline_terminal(
    tmp_path: Path,
) -> None:
    context = _context()
    candidates = [
        {
            "candidate_id": "post-meta-source-family-sort-init-indexed-write-name-total-locals",
            "candidate_path": "/tmp/legacy-init.c",
            "dimension_id": "sort-init-indexed-write",
        },
        {
            "candidate_id": "post-meta-source-family-sort-swap-slot-lvalue-direct-assets",
            "candidate_path": "/tmp/legacy-swap.c",
            "dimension_id": "sort-swap-slot-lvalue",
        },
    ]
    scores = [
        _score(candidate, actual34=4, actual44=23, accepted=False)
        for candidate in candidates
    ]

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload.get("terminal_reason") != (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_TERMINAL_REASON
    )
    assert payload.get("next_unsupported_source_family") != (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )


def test_sort_post_inline_boundary_selection_emission_zero_generation_terminalizes_only_new_dimension(
    tmp_path: Path,
) -> None:
    context = _sort_post_inline_boundary_selection_emission_context(tmp_path)

    payload = build_generated_source_family_payload(
        [],
        context,
        continue_after_final_source_family=True,
    )

    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_family"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_FINAL_FAMILY
    )
    assert payload["generation_blockers"][0]["reason"] == (
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_PATTERN_BLOCKER
    )
    blocker = payload["generation_blockers"][0]
    assert [row["dimension_id"] for row in payload["exhausted_dimensions"]] == [
        SORT_POST_INLINE_BOUNDARY_SELECTION_EMISSION_SOURCE_SHAPE_DIMENSION
    ]
    assert blocker["seed_pcdump_path"]


def test_sort_post_cross_tu_sentinel_without_evidence_is_not_terminal(
    tmp_path: Path,
) -> None:
    proof = _sort_post_cross_tu_terminal_proof()
    proof["candidate_scores"] = []
    proof["terminal_blockers"] = []
    synthesis_payload = proof["source_family_synthesis"]
    synthesis_payload["retained_scored_probes"] = []
    synthesis_payload["candidate_scores"] = []
    synthesis_payload["source_hunks_by_candidate"] = []
    synthesis_payload["one_hit_summary"] = {}
    synthesis_payload["terminal_blockers"] = []
    context = normalize_meta_ceiling_context(
        [proof],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )

    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=1,
        include_source=True,
    )
    payload = build_generated_source_family_payload([], context)

    assert candidates
    assert payload["status"] != "terminal"
    assert not (
        payload.get("status") == "terminal"
        and payload.get("next_unsupported_source_family")
        == synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )


def test_cli_source_model_synthesis_writes_unbounded_tu_data_ownership_probes(
    tmp_path: Path,
) -> None:
    context = _sort_tu_source_context(tmp_path)
    tu_candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    tu_terminal = classify_source_family_scores(
        tu_candidates,
        [
            _score(candidate, actual34=24, actual44=None, accepted=True)
            for candidate in tu_candidates
        ],
        context,
    )
    meta = tmp_path / "sort-tu-terminal.json"
    meta.write_text(json.dumps(tu_terminal), encoding="utf-8")
    source = tmp_path / "sort.c"
    source.write_text(_sort_source(), encoding="utf-8")
    output = tmp_path / "unbounded-tu-data-ownership-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(output),
            "--max-per-dimension",
            "10",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] > 0
    dimension = next(
        row
        for row in payload["dimensions"]
        if row["dimension_id"]
        == synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
    )
    assert dimension["candidate_count"] > 0
    paths = [Path(row["candidate_path"]) for row in payload["candidates"]]
    assert all(path.is_file() for path in paths)
    assert all(
        "--full-unit-source" in row["score_command"] for row in payload["candidates"]
    )
    texts = [path.read_text() for path in paths]
    assert any("mnDiagram_PostMetaSortUnbounded" in text for text in texts)
    assert any(
        text.index("mnDiagram_PostMetaSortUnbounded")
        < text.index("void mnDiagram_8023FC28(void)")
        for text in texts
    )


def test_cli_source_model_synthesis_cross_tu_handoff_terminalizes_no_lower_families(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "sort-unbounded-terminal.json"
    meta.write_text(
        json.dumps(_sort_unbounded_tu_data_ownership_terminal_payload(tmp_path)),
        encoding="utf-8",
    )
    source = tmp_path / "sort.c"
    source.write_text(_sort_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--continue-after-final-source-family",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["source_model_proof"]["source_family_synthesis"][
        "exhausted_source_dimension"
    ] == synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION
    assert not {row.get("dimension_id") for row in payload.get("candidates", [])} & (
        OLD_SORT_DIMENSIONS | NATURAL_SORT_DIMENSIONS | SEMANTIC_SORT_DIMENSIONS
    )


def test_retained_frontier_normalizes_tu_source_context_terminal_proof(
    tmp_path: Path,
) -> None:
    context = _sort_tu_source_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    terminal = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=24, actual44=27, accepted=True)
            for candidate in candidates
        ],
        context,
    )
    artifact = tmp_path / "sort-tu-source-context-terminal.json"
    artifact.write_text(json.dumps(terminal), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    proof_synthesis = proof["source_family_synthesis"]
    assert (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
        in (proof_synthesis["attempted_equivalence_classes"])
    )
    assert proof["next_unsupported_source_model"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert proof["next_unsupported_source_family"] == (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)
    assert result["status"] == "practical-ceiling"
    ceiling_synthesis = result["current_ceiling"]["source_family_synthesis"]
    assert (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
        in (ceiling_synthesis["attempted_equivalence_classes"])
    )
    assert any(
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
        in step
        for step in result["next_steps"]
    )


def test_retained_frontier_prefers_unbounded_tu_data_ownership_over_stale_tu_context(
    tmp_path: Path,
) -> None:
    tu_context = _sort_tu_source_context(tmp_path)
    tu_candidates = generate_source_family_candidates(
        _sort_source(),
        tu_context,
        max_per_dimension=10,
        include_source=True,
    )
    stale_tu_terminal = classify_source_family_scores(
        tu_candidates,
        [
            _score(candidate, actual34=24, actual44=None, accepted=True)
            for candidate in tu_candidates
        ],
        tu_context,
    )
    unbounded_context = normalize_meta_ceiling_context(
        [stale_tu_terminal],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
    unbounded_candidates = generate_source_family_candidates(
        _sort_source(),
        unbounded_context,
        max_per_dimension=10,
        include_source=True,
    )
    unbounded_terminal = classify_source_family_scores(
        unbounded_candidates,
        [
            _score(candidate, actual34=24, actual44=31, accepted=True)
            for candidate in unbounded_candidates
        ],
        unbounded_context,
    )
    stale_artifact = tmp_path / "sort-stale-tu-terminal.json"
    stale_artifact.write_text(json.dumps(stale_tu_terminal), encoding="utf-8")
    unbounded_artifact = tmp_path / "sort-unbounded-terminal.json"
    unbounded_artifact.write_text(json.dumps(unbounded_terminal), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[stale_artifact, unbounded_artifact],
    )

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    synthesis_payload = proof["source_family_synthesis"]
    assert (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
        in (synthesis_payload["attempted_equivalence_classes"])
    )
    assert proof["next_unsupported_source_family"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert proof["next_unsupported_source_family"] != (
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)
    assert result["status"] == "practical-ceiling"
    ceiling = result["current_ceiling"]
    assert ceiling["next_unsupported_source_family"] == (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert any(
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY in step
        for step in result["next_steps"]
    )
    assert not any(
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_EXHAUSTED_NEXT_FAMILY
        in step
        for step in result["next_steps"]
    )


def test_cli_source_model_synthesis_writes_helper_data_layout_context_probes(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "sort-whole-function-terminal.json"
    meta.write_text(
        json.dumps(_sort_whole_function_control_data_flow_terminal_payload(tmp_path)),
        encoding="utf-8",
    )
    source = tmp_path / "sort.c"
    source.write_text(_sort_source(), encoding="utf-8")
    output = tmp_path / "helper-data-layout-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(output),
            "--max-per-dimension",
            "10",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert {row["dimension_id"] for row in payload["candidates"]} == {
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
    }
    paths = [Path(row["candidate_path"]) for row in payload["candidates"]]
    assert all(path.is_file() for path in paths)
    texts = [path.read_text() for path in paths]
    assert any("mnDiagram_PostMetaSortCandidateBetter" in text for text in texts)
    assert any("mnDiagram_PostMetaSortLayout" in text for text in texts)
    assert all(
        "--full-unit-source" in row["score_command"] for row in payload["candidates"]
    )
    assert all(
        (text.index("static inline") < text.index("void mnDiagram_8023FC28(void)"))
        or (
            text.index("typedef struct mnDiagram_PostMetaSortLayout")
            < text.index("void mnDiagram_8023FC28(void)")
        )
        for text in texts
    )


def test_cli_source_model_synthesis_writes_whole_function_sort_probes(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "sort-full-selection-terminal.json"
    meta.write_text(
        json.dumps(_sort_full_selection_swap_terminal_payload()),
        encoding="utf-8",
    )
    source = tmp_path / "sort.c"
    source.write_text(_sort_source(), encoding="utf-8")
    output = tmp_path / "whole-function-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(output),
            "--max-per-dimension",
            "10",
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] > 0
    whole_function = [
        row
        for row in payload["candidates"]
        if row["dimension_id"]
        == synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
    ]
    assert whole_function
    paths = [Path(row["candidate_path"]) for row in whole_function]
    assert all(path.is_file() for path in paths)
    assert any("void mnDiagram_8023FC28(void)" in path.read_text() for path in paths)


def test_allocator_ceiling_prefers_full_selection_exhaustion_over_stale_continuation(
    tmp_path: Path,
) -> None:
    stale_next_model = synthesis.SORT_FULL_SELECTION_SWAP_UNSUPPORTED_SOURCE_MODEL
    stale = {
        "function": SORT_FUNCTION,
        "status": "terminal",
        "terminal": True,
        "kind": "post-ceiling-continuation-exhausted",
        "family_id": "post-ceiling-source-model-proof",
        "terminal_reason": (
            "post-meta-gpr-one-hit-source-family-continuation-exhausted/protected-structural-ceiling"
        ),
        "final_force_phys": {"34": 27, "44": 25},
        "terminal_blockers": [
            synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
        ],
        "source_model_proof": {
            "next_unsupported_source_model": stale_next_model,
            "terminal_blockers": [
                synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
            ],
            "source_family_synthesis": {
                "status": "synthesis-exhausted",
                "evidence_status": "artifact-synthesis-data",
                "attempted_equivalence_classes": [
                    "sort-protected-loss-init-lifetime",
                    synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION,
                ],
                "exhausted_dimensions": [
                    {"dimension_id": "sort-protected-loss-init-lifetime"},
                    {"dimension_id": (synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION)},
                ],
                "terminal_blockers": [
                    synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER
                ],
                "next_unsupported_source_model": stale_next_model,
            },
        },
    }
    stale_artifact = tmp_path / "sort-stale-continuation.json"
    stale_artifact.write_text(json.dumps(stale), encoding="utf-8")
    full_selection_artifact = tmp_path / "sort-full-selection-source-model.json"
    full_selection_artifact.write_text(
        json.dumps(_sort_full_selection_swap_terminal_payload()),
        encoding="utf-8",
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[stale_artifact, full_selection_artifact],
    )
    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)

    assert result["status"] == "practical-ceiling"
    ceiling = result["current_ceiling"]
    assert (
        ceiling["next_unsupported_source_model"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_MODEL
    )
    assert (
        ceiling["next_unsupported_source_family"]
        == synthesis.SORT_FULL_SELECTION_SWAP_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        synthesis.SORT_FULL_SELECTION_SWAP_DIMENSION
        in (ceiling["source_family_synthesis"]["attempted_equivalence_classes"])
    )
    assert synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER not in (
        ceiling.get("terminal_blockers") or []
    )
    assert synthesis.SORT_FULL_SELECTION_SWAP_SOURCE_REGION_PATTERN_BLOCKER not in (
        ceiling["source_family_synthesis"].get("terminal_blockers") or []
    )


def test_allocator_ceiling_prefers_whole_function_handoff_over_stale_full_selection(
    tmp_path: Path,
) -> None:
    stale_artifact = tmp_path / "sort-stale-full-selection.json"
    stale_artifact.write_text(
        json.dumps(_sort_full_selection_swap_terminal_payload()),
        encoding="utf-8",
    )
    whole_artifact = tmp_path / "sort-whole-function-terminal.json"
    whole_artifact.write_text(
        json.dumps(_sort_whole_function_control_data_flow_terminal_payload(tmp_path)),
        encoding="utf-8",
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[stale_artifact, whole_artifact],
    )
    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)

    assert result["status"] == "practical-ceiling"
    ceiling = result["current_ceiling"]
    assert ceiling["next_unsupported_source_model"] == (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_MODEL
    )
    assert ceiling["next_unsupported_source_family"] == (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY
    )
    assert (
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_DIMENSION
        in (ceiling["source_family_synthesis"]["attempted_equivalence_classes"])
    )
    assert any(
        synthesis.SORT_WHOLE_FUNCTION_CONTROL_DATA_FLOW_EXHAUSTED_NEXT_FAMILY in step
        for step in result["next_steps"]
    )
    assert not any(
        synthesis.SORT_FULL_SELECTION_SWAP_UNSUPPORTED_SOURCE_MODEL in step
        for step in result["next_steps"]
    )


def test_retained_frontier_normalizes_helper_data_layout_source_context_dimensions(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    helper_payload = classify_source_family_scores(
        candidates,
        [
            _score(candidate, actual34=27, actual44=22, accepted=True)
            for candidate in candidates
        ],
        context,
    )
    artifact = tmp_path / "sort-helper-data-layout-terminal.json"
    artifact.write_text(json.dumps(helper_payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )

    function = triaged["functions"][0]
    proof = function["meta_ceiling"]["terminal_proof"]
    assert (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
        in (proof["source_family_synthesis"]["attempted_equivalence_classes"])
    )
    assert proof["next_unsupported_source_model"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert proof["next_unsupported_source_family"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)
    assert result["status"] == "practical-ceiling"
    ceiling = result["current_ceiling"]
    assert ceiling["next_unsupported_source_model"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    assert ceiling["next_unsupported_source_family"] == (
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    next_context = normalize_meta_ceiling_context(
        [result],
        function=SORT_FUNCTION,
        repo_root=tmp_path,
    )
    next_candidates = generate_source_family_candidates(
        _sort_source(),
        next_context,
        max_per_dimension=10,
        include_source=True,
    )
    assert next_candidates
    assert {row["dimension_id"] for row in next_candidates} == {
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
    }
    next_candidate_ids = {row["candidate_id"] for row in next_candidates}
    assert "post-meta-sort-tu-source-context-storage-overlay-accessor" in (
        next_candidate_ids
    )
    assert "post-meta-sort-tu-source-context-shared-name-accessor" in (
        next_candidate_ids
    )
    assert all(
        row["validation_metadata"]["requires_full_unit_source"] is True
        and row["validation_metadata"]["requires_structural_guard"] is True
        and row["validation_metadata"]["required_preserved_assignments"]
        == ["IG34->r27", "IG44->r25"]
        for row in next_candidates
    )


def test_sort_protected_loss_repair_lane_triages_as_retained_frontier(
    tmp_path: Path,
) -> None:
    continuation_payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_combine_real_score_protected_loss_terminal()],
    )
    artifact = tmp_path / "sort-protected-loss-continuation.json"
    artifact.write_text(json.dumps(continuation_payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )

    assert triaged["status"] == "actionable"
    next_frontier = triaged["next_frontier"]
    assert next_frontier["family_id"] == "post-ceiling-source-model-proof"
    assert next_frontier["continuation"]["route"] == (
        "sort-semantic-protected-loss-repair"
    )
    assert next_frontier["continuation"]["source_retained"] == (
        "build/sort/repair-selected-name-owner-dst.c"
    )
    assert next_frontier["continuation"]["pcdump_path"].endswith(".pcdump.txt")
    assert triaged["functions"][0]["meta_ceiling"]["status"] == "actionable"


def test_allocator_ceiling_preserves_sort_protected_loss_repair_lane(
    tmp_path: Path,
) -> None:
    continuation_payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows()),
        [_sort_combine_real_score_protected_loss_terminal()],
    )
    artifact = tmp_path / "sort-protected-loss-continuation.json"
    artifact.write_text(json.dumps(continuation_payload), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == (
        "retained-frontiers-next-source-actionable-lane"
    )
    assert (
        result["retained_frontiers_meta_ceiling"]["next_frontier"]["continuation"][
            "route"
        ]
        == "sort-semantic-protected-loss-repair"
    )
    assert any(
        "repair-selected-name-owner-dst.c" in step for step in result["next_steps"]
    )
    assert any("debug target score-source" in step for step in result["next_steps"])


def test_sort_semantic_source_model_estimate_only_recombine_does_not_triage_actionable(
    tmp_path: Path,
) -> None:
    context = _sort_semantic_context()
    candidates = []
    scores = []
    for index, dimension in enumerate(SEMANTIC_SORT_DIMENSIONS):
        hit_virtual = "34" if index == 0 else "44" if index == 1 else None
        candidate = {
            "candidate_id": f"semantic-{dimension}",
            "dimension_id": dimension,
            "equivalence_class": dimension,
            "variant_id": dimension,
            "source_hunks": [
                _sort_semantic_hunk(
                    10 if index == 0 else 20 if index == 1 else 40 + index
                )
            ],
            "source_components": [_sort_semantic_component(f"sort-component-{index}")],
            "source_retained": f"{dimension}.c",
        }
        candidates.append(candidate)
        if hit_virtual is None:
            scores.append(_score(candidate, accepted=False))
        elif hit_virtual == "34":
            scores.append(_score(candidate, actual34=27, actual44=22, accepted=False))
        else:
            scores.append(_score(candidate, actual34=22, actual44=25, accepted=False))

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "terminal"
    assert payload["semantic_recombine"]["status"] == "actionable"
    top = payload["semantic_recombine"]["ranked_candidates"][0]
    assert top["target_score_estimate"]["matched"] == 2
    assert top["source_hunks"]
    proof_synthesis = payload["source_model_proof"]["source_family_synthesis"]
    proof_recombine = proof_synthesis.get("semantic_recombine")
    assert proof_recombine["status"] == "actionable"
    proof_top = proof_recombine["ranked_candidates"][0]
    assert proof_top["dimension_id"] == "sort-semantic-dual-target-recombine"
    assert proof_top["source_hunks"]

    artifact = tmp_path / "sort-source-model-terminal-actionable-recombine.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )
    assert triaged["status"] == "all-known-frontiers-exhausted"
    assert triaged["next_frontier"] is None
    assert triaged["functions"][0]["frontiers"] == []
    assert triaged["functions"][0]["meta_ceiling"]["status"] == (
        "terminal-current-source-shape-ceiling"
    )

    result = classify_allocator_ceiling([triaged], function=SORT_FUNCTION)
    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    assert not any("source hunk" in step for step in result["next_steps"])


def test_sort_semantic_overlapping_recombine_terminal_blockers() -> None:
    rows = [
        _sort_one_hit_row(
            "post-meta-sort-semantic-owner-dst-local-only",
            "sort-semantic-loop-ownership",
            hit_virtual="34",
            hunk_start=10,
            component_id="sort-selected-emission",
            source_retained="ig34.c",
        ),
        _sort_one_hit_row(
            "post-meta-sort-semantic-selected-name-after-inner",
            "sort-semantic-selected-name-extraction",
            hit_virtual="44",
            hunk_start=10,
            component_id="sort-selected-emission",
            source_retained="ig44.c",
        ),
    ]

    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified_with_rows(rows),
        [],
    )

    assert payload["status"] == "terminal"
    assert payload["semantic_recombine"]["status"] == "terminal"
    blockers = payload["semantic_recombine"]["ranked_candidates"][0]["blockers"]
    assert "recombine-overlapping-source-hunks" in blockers
    assert "semantic-component-conflict:sort-selected-emission" in blockers
    assert SORT_SEMANTIC_RECOMBINE_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }


def test_sort_semantic_score_rows_rank_dual_target_progress(
    tmp_path: Path,
) -> None:
    context = _sort_semantic_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "semantic-actionable-probes",
    )
    semantic = [
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    ]
    winner = semantic[0]
    scores = [_score(row) for row in semantic]
    scores[0] = _score(winner, actual34=27, actual44=25)

    payload = classify_source_family_scores(semantic, scores, context)

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == winner["candidate_id"]
    assert payload["best_candidate"]["target_matched"] == 2
    virtuals = payload["best_candidate"]["target_score"]["virtuals"]
    assert virtuals["34"]["matched"] is True
    assert virtuals["44"]["matched"] is True


def test_score_rows_keep_subprocess_failure_metadata(tmp_path: Path) -> None:
    context = _context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "probes",
    )
    score = {
        "candidate_id": candidates[0]["candidate_id"],
        "source_file": candidates[0]["candidate_path"],
        "error": "score-source-json-parse-error",
        "score_returncode": 2,
        "score_stderr": "No such option: --expression-source",
        "raw_stdout": "",
    }

    payload = classify_source_family_scores(candidates, [score], context)
    row = payload["score_rows"][0]

    assert payload["status"] == "incomplete"
    assert row["score_error"] == "score-source-json-parse-error"
    assert row["score_returncode"] == 2
    assert row["score_stderr"] == "No such option: --expression-source"
    assert row["raw_stdout"] == ""


def test_missing_score_row_is_incomplete(tmp_path: Path) -> None:
    context = _context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "probes",
    )

    payload = classify_source_family_scores(
        candidates,
        [_score(row) for row in candidates[:-1]],
        context,
    )

    assert payload["status"] == "incomplete"
    assert payload["reason"] == "not-all-generated-candidates-scored"
    assert payload["missing_score_candidate_ids"] == [candidates[-1]["candidate_id"]]


def test_live_score_uses_parent_tool_package_before_worktree_tooling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "matcher"
    stale_tools = repo_root / "tools" / "melee-agent"
    stale_tools.mkdir(parents=True)
    candidate_path = repo_root / "build" / "candidate.c"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("void f(void) {}\n", encoding="utf-8")
    target = repo_root / "target.json"
    target.write_text("{}", encoding="utf-8")
    expression_baseline = repo_root / "baseline.pcdump.txt"
    expression_baseline.write_text("", encoding="utf-8")
    source = repo_root / "src" / "melee" / "mn" / "mndiagram.c"
    source.parent.mkdir(parents=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    candidate = {
        "candidate_id": "probe-1",
        "dimension_id": "sort-init-indexed-write",
        "source_model_layer_dimension_id": "sort-init-indexed-write",
        "candidate_path": str(candidate_path),
    }
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["pythonpath"] = env["PYTHONPATH"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"target_score": {"matched": 0, "targeted": 2}}),
            stderr="",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)
    monkeypatch.setenv("PYTHONPATH", str(stale_tools))

    rows = score_source_candidates(
        [candidate],
        repo_root=repo_root,
        context=_context(),
        target=target,
        cflags_from=source,
        expression_source=source,
        expression_baseline=expression_baseline,
    )

    package_tools = str(Path(synthesis.__file__).resolve().parents[2])
    cmd = captured["cmd"]
    entries = str(captured["pythonpath"]).split(os.pathsep)
    assert captured["cwd"] == repo_root
    assert entries[0] == package_tools
    assert str(stale_tools.resolve()) in entries[1:]
    assert cmd[cmd.index("--expression-baseline") + 1] == str(expression_baseline)
    assert rows[0]["candidate_id"] == "probe-1"
    assert rows[0]["dimension_id"] == "sort-init-indexed-write"
    assert rows[0]["source_model_layer_dimension_id"] == "sort-init-indexed-write"
    assert rows[0]["function"] == SORT_SOURCE_FUNCTION
    assert rows[0]["score_function"] == SORT_SOURCE_FUNCTION
    assert rows[0]["source_file"] == str(candidate_path)
    assert rows[0]["source_retained"] == str(candidate_path)
    assert rows[0]["c_file"] == str(candidate_path)
    assert rows[0]["cflags_from"] == str(source)
    assert rows[0]["target_score"]["matched"] == 0


def test_live_score_appends_full_unit_for_helper_data_layout_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "matcher"
    candidate_path = repo_root / "build" / "candidate.c"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("void mnDiagram_8023FC28(void) {}\n", encoding="utf-8")
    target = repo_root / "target.json"
    target.write_text("{}", encoding="utf-8")
    source = repo_root / "src" / "melee" / "mn" / "mndiagram.c"
    source.parent.mkdir(parents=True)
    source.write_text("void mnDiagram_8023FC28(void) {}\n", encoding="utf-8")
    candidate = {
        "candidate_id": "post-meta-sort-source-context-shift-emission-helper",
        "candidate_path": str(candidate_path),
        "dimension_id": synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION,
        "validation_metadata": {
            "requires_full_unit_source": True,
            "score_function": SORT_SOURCE_FUNCTION,
        },
    }
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "target_score": {
                        "matched": 2,
                        "targeted": 2,
                        "virtual_distance": 0,
                        "virtuals": {
                            "34": {"expected": 27, "actual": 27, "matched": True},
                            "44": {"expected": 25, "actual": 25, "matched": True},
                        },
                    },
                    "structural_guard": {"accepted": True},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)

    rows = score_source_candidates(
        [candidate],
        repo_root=repo_root,
        context=_context(),
        target=target,
        cflags_from=source,
        expression_source=source,
    )
    payload = classify_source_family_scores([candidate], rows, _context())

    cmd = captured["cmd"]
    assert "--full-unit-source" in cmd
    assert "--checkdiff-guard" in cmd
    assert rows[0]["full_unit_source"] is True
    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == candidate["candidate_id"]


def test_live_score_omits_full_unit_for_target_function_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "matcher"
    candidate_path = repo_root / "build" / "candidate.c"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("void mnDiagram_8023FC28(void) {}\n", encoding="utf-8")
    target = repo_root / "target.json"
    target.write_text("{}", encoding="utf-8")
    source = repo_root / "src" / "melee" / "mn" / "mndiagram.c"
    source.parent.mkdir(parents=True)
    source.write_text("void mnDiagram_8023FC28(void) {}\n", encoding="utf-8")
    candidate = {
        "candidate_id": "target-function-probe",
        "candidate_path": str(candidate_path),
    }
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "target_score": {"matched": 0, "targeted": 2},
                    "structural_guard": {"accepted": True},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)

    rows = score_source_candidates(
        [candidate],
        repo_root=repo_root,
        context=_context(),
        target=target,
        cflags_from=source,
        expression_source=source,
    )

    assert "--full-unit-source" not in captured["cmd"]
    assert rows[0]["full_unit_source"] is False


def test_helper_data_layout_helper_definition_errors_stay_blocked_with_diagnostic(
    tmp_path: Path,
) -> None:
    context = _sort_helper_data_layout_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    scores = []
    for candidate in candidates:
        row = _score(candidate, actual34=27, actual44=25, accepted=True)
        row["score_returncode"] = 0
        row["structural_guard_error"] = (
            "candidate source defines helper function(s) outside mnDiagram_8023FC28: mnDiagram_PostMetaSortShiftInsert"
        )
        scores.append(row)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "score-rows-not-terminal-safe"
    blocker_reasons = {
        row["reason"] for row in payload["blockers"] if isinstance(row, dict)
    }
    assert "score-row-error" in blocker_reasons
    assert "source-context-scored-without-full-unit-source" in blocker_reasons
    source_context_blocker = next(
        row
        for row in payload["blockers"]
        if row.get("reason") == "source-context-scored-without-full-unit-source"
    )
    assert source_context_blocker["legacy_reason"] == (
        "helper-data-layout-scored-without-full-unit-source"
    )
    assert source_context_blocker["dimension_ids"] == [
        synthesis.SORT_HELPER_DATA_LAYOUT_CONTEXT_DIMENSION
    ]


def test_sort_tu_context_helper_definition_errors_stay_blocked_with_diagnostic(
    tmp_path: Path,
) -> None:
    context = _sort_tu_source_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    scores = []
    for candidate in candidates:
        row = _score(candidate, actual34=27, actual44=25, accepted=True)
        row["score_returncode"] = 0
        row["structural_guard_error"] = (
            "candidate source defines helper function(s) outside mnDiagram_8023FC28: mnDiagram_PostMetaSortTUStorageRef"
        )
        scores.append(row)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "score-rows-not-terminal-safe"
    source_context_blocker = next(
        row
        for row in payload["blockers"]
        if row.get("reason") == "source-context-scored-without-full-unit-source"
    )
    assert source_context_blocker["legacy_reason"] == (
        "helper-data-layout-scored-without-full-unit-source"
    )
    assert source_context_blocker["dimension_ids"] == [
        synthesis.SORT_TU_DATA_SYMBOL_HELPER_BOUNDARY_CONTEXT_DIMENSION
    ]


def test_sort_unbounded_tu_context_helper_definition_errors_stay_blocked_with_diagnostic(
    tmp_path: Path,
) -> None:
    context = _sort_unbounded_tu_data_ownership_context(tmp_path)
    candidates = generate_source_family_candidates(
        _sort_source(),
        context,
        max_per_dimension=10,
        include_source=True,
    )
    scores = []
    for candidate in candidates:
        row = _score(candidate, actual34=27, actual44=25, accepted=True)
        row["score_returncode"] = 0
        row["structural_guard_error"] = (
            "candidate source defines helper function(s) outside "
            "mnDiagram_8023FC28: mnDiagram_PostMetaSortUnboundedTUOwnerRef"
        )
        scores.append(row)

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "score-rows-not-terminal-safe"
    source_context_blocker = next(
        row
        for row in payload["blockers"]
        if row.get("reason") == "source-context-scored-without-full-unit-source"
    )
    assert source_context_blocker["dimension_ids"] == [
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_DIMENSION
    ]


def test_live_score_returns_partial_row_on_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "matcher"
    source = repo_root / "src" / "melee" / "mn" / "mndiagram.c"
    source.parent.mkdir(parents=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    target = repo_root / "target.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    candidates = []
    for index in range(3):
        candidate_path = repo_root / "build" / f"candidate-{index}.c"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text("void f(void) {}\n", encoding="utf-8")
        candidates.append(
            {
                "candidate_id": f"probe-{index}",
                "candidate_path": str(candidate_path),
            }
        )
    calls = 0

    def fake_run(cmd, *, cwd, env, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "target_score": {"matched": 0, "targeted": 2},
                    "structural_guard": {"accepted": True},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)

    rows = score_source_candidates(
        candidates,
        repo_root=repo_root,
        context=_context(),
        target=target,
        cflags_from=source,
        expression_source=source,
    )
    payload = classify_source_family_scores(candidates, rows, _context())

    assert calls == 2
    assert len(rows) == 2
    assert rows[-1]["candidate_id"] == "probe-1"
    assert rows[-1]["error"] == "score-source-interrupted"
    assert rows[-1]["score_returncode"] == 130
    assert payload["status"] == "incomplete"
    assert payload["partial_score"]["reason"] == "live-score-interrupted"
    assert payload["terminal_blocker"] == "score-source-keyboard-interrupt"
    assert payload["interruption"]["exit_code"] == 130
    assert payload["partial_score"]["last_candidate_id"] == "probe-1"
    assert payload["last_candidate"]["candidate_id"] == "probe-1"
    assert payload["missing_score_candidate_ids"] == ["probe-2"]
    assert any(
        blocker["reason"] == "live-score-interrupted" for blocker in payload["blockers"]
    )


def test_live_score_returns_partial_row_on_subprocess_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "matcher"
    source = repo_root / "src" / "melee" / "mn" / "mndiagram.c"
    source.parent.mkdir(parents=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    target = repo_root / "target.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    candidate_path = repo_root / "build" / "candidate.c"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text("void f(void) {}\n", encoding="utf-8")
    candidates = [
        {
            "candidate_id": "probe-timeout",
            "candidate_path": str(candidate_path),
        }
    ]

    def fake_run(cmd, *, cwd, env, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd,
            timeout=5.0,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)

    rows = score_source_candidates(
        candidates,
        repo_root=repo_root,
        context=_context(),
        target=target,
        cflags_from=source,
        expression_source=source,
        timeout=1,
    )
    payload = classify_source_family_scores(candidates, rows, _context())

    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "probe-timeout"
    assert rows[0]["error"] == "score-source-timeout"
    assert rows[0]["score_returncode"] == 124
    assert rows[0]["raw_stdout"] == "partial stdout"
    assert rows[0]["score_stderr"] == "partial stderr"
    assert payload["status"] == "incomplete"
    assert payload["partial_score"]["reason"] == "live-score-timeout"
    assert payload["terminal_blocker"] == "score-source-timeout"
    assert payload["interruption"]["exit_code"] == 124
    assert payload["partial_score"]["timeout_seconds"] == 5.0


def test_draw_all_scored_without_progress_emits_fpr_terminal_proof(
    tmp_path: Path,
) -> None:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-probes",
    )

    payload = classify_source_family_scores(
        candidates,
        [_draw_score(row) for row in candidates],
        context,
    )

    assert payload["status"] == "terminal"
    assert payload["kind"] == "post-ceiling-fpr-expression-source-model-synthesis-proof"
    assert payload["terminal_summary"]["kind"] == "no-post-ceiling-draw-source-family"
    source_model = payload["source_model_proof"]
    assert source_model["register_class"] == "fpr"
    assert source_model["source_family_synthesis"]["status"] == "synthesis-exhausted"
    assert source_model["source_family_synthesis"]["evidence_status"] == (
        "artifact-synthesis-data"
    )
    assert set(
        source_model["source_family_synthesis"]["attempted_equivalence_classes"]
    ) >= {
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
        "draw-expression-lifetime-product-operand-ownership",
    }
    expressions = {
        row["virtual"]: row["expression"] for row in source_model["expression_anchors"]
    }
    assert expressions[32] == "y_spacing * (f32) col"
    assert expressions[37] == "HSD_JObjGetTranslationY(jobj2) - base"
    assert expressions[46] == "fsubs f46,f45,f44"

    artifact = tmp_path / "draw-terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )
    frontier = next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert (
        frontier["kind"] == "post-ceiling-fpr-expression-source-model-synthesis-proof"
    )
    assert frontier["attempted_targets"] == {"32": 28, "37": 26, "46": 26}


def test_draw_terminal_proof_records_expression_lifetime_attempted_classes(
    tmp_path: Path,
) -> None:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-expression-probes",
    )
    scores = [_draw_score(row) for row in candidates]

    incomplete = classify_source_family_scores(candidates, scores[:-1], context)
    assert incomplete["status"] == "incomplete"
    assert "unsupported_source_expression_class" not in incomplete

    payload = classify_source_family_scores(candidates, scores, context)

    assert payload["status"] == "terminal"
    assert payload["kind"] == "post-ceiling-fpr-expression-source-model-synthesis-proof"
    synthesis = payload["source_model_proof"]["source_family_synthesis"]
    attempted = set(synthesis["attempted_equivalence_classes"])
    assert {
        "draw-col-cast-product-local",
        "draw-row-translation-scale-split",
        "draw-digit-callarg-fsubs-temp",
        "draw-expression-lifetime-product-operand-ownership",
        "draw-expression-lifetime-product-sink-ownership",
        "draw-expression-lifetime-row-offset-sink-branch-ownership",
        "draw-expression-lifetime-digit-guarded-statement-motion",
    } <= attempted
    assert attempted == {
        row["dimension_id"] for row in synthesis["exhausted_dimensions"]
    }
    assert (
        payload["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS
    )
    assert (
        synthesis["unsupported_source_expression_class"]
        == DRAW_COUPLED_UNSUPPORTED_CLASS
    )


def test_all_scored_without_progress_emits_triage_compatible_terminal_proof(
    tmp_path: Path,
) -> None:
    context = _context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "probes",
    )

    payload = classify_source_family_scores(
        candidates,
        [_score(row) for row in candidates],
        context,
    )

    assert payload["status"] == "terminal"
    assert payload["terminal_summary"]["kind"] == "no-post-ceiling-sort-source-family"
    assert payload["source_model_proof"]["source_family_synthesis"]["status"] == (
        "synthesis-exhausted"
    )
    exhausted = {row["dimension_id"] for row in payload["exhausted_dimensions"]}
    assert OLD_SORT_DIMENSIONS <= exhausted
    assert NATURAL_SORT_DIMENSIONS <= exhausted
    assert (
        "broader natural C sort rewrite" not in payload["next_unsupported_source_model"]
    )
    artifact = tmp_path / "terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )
    frontier = next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert frontier["family_id"] == "post-ceiling-source-model-proof"
    assert frontier["source_model_proof"]["source_family_synthesis"]["status"] == (
        "synthesis-exhausted"
    )


def _draw_adapted_structural_guard_terminal_payload(tmp_path: Path) -> dict:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-adapted-probes",
    )
    adapted = [
        row
        for row in candidates
        if str(row["dimension_id"]).startswith("draw-expression-lifetime-")
    ]
    assert adapted

    return classify_source_family_scores(
        adapted,
        [_draw_score(row, accepted=False) for row in adapted],
        context,
    )


def test_draw_adapted_structural_guard_rejections_terminalize_with_blockers(
    tmp_path: Path,
) -> None:
    payload = _draw_adapted_structural_guard_terminal_payload(tmp_path)

    assert payload["status"] == "terminal"
    assert payload.get("reason") != "score-rows-not-terminal-safe"
    assert payload["blockers"][0]["reason"] == "structural-guard-not-accepted"
    assert payload["score_count"] == payload["joined_score_count"]
    assert payload["missing_score_candidate_ids"] == []
    assert payload["metadata_mismatches"] == []
    assert (
        payload["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS
    )
    assert payload["next_unsupported_source_model"] == DRAW_COUPLED_UNSUPPORTED_MODEL

    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    retained = synthesis_payload["retained_scored_probes"]
    assert retained
    assert all(row["target_score"] for row in retained)
    assert all(row["structural_guard_accepted"] is False for row in retained)
    assert all(row["adapted_from_expression_interferer"] is True for row in retained)
    assert all(row["requires_expression_score_validation"] is True for row in retained)
    assert {row["dimension_id"] for row in payload["exhausted_dimensions"]} == {
        row["dimension_id"] for row in retained
    }


def _draw_mixed_legacy_adapted_structural_guard_terminal_payload(
    tmp_path: Path,
) -> dict:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-mixed-probes",
    )
    legacy = next(
        row
        for row in candidates
        if row["dimension_id"] == "draw-col-cast-product-local"
    )
    adapted = next(
        row
        for row in candidates
        if str(row["dimension_id"]).startswith("draw-expression-lifetime-")
    )

    return classify_source_family_scores(
        [legacy, adapted],
        [
            _draw_score(legacy, accepted=False),
            _draw_score(adapted, accepted=False),
        ],
        context,
    )


def test_draw_mixed_legacy_adapted_zero_progress_terminalizes_with_blockers(
    tmp_path: Path,
) -> None:
    payload = _draw_mixed_legacy_adapted_structural_guard_terminal_payload(tmp_path)

    assert payload["status"] == "terminal"
    assert payload.get("reason") != "score-rows-not-terminal-safe"
    assert payload["score_count"] == payload["joined_score_count"]
    assert payload["missing_score_candidate_ids"] == []
    assert payload["metadata_mismatches"] == []
    assert payload["blockers"][0]["reason"] == "structural-guard-not-accepted"
    assert (
        payload["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS
    )

    exhausted = {row["dimension_id"] for row in payload["exhausted_dimensions"]}
    assert "draw-col-cast-product-local" in exhausted
    assert any(
        str(dimension).startswith("draw-expression-lifetime-")
        for dimension in exhausted
    )
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    retained = synthesis_payload["retained_scored_probes"]
    assert retained
    assert {row["dimension_id"] for row in retained} == exhausted
    assert all(row["target_score"] for row in retained)
    assert all(row["target_matched"] == 0 for row in retained)
    assert all(row["expression_matched"] == 0 for row in retained)
    assert synthesis_payload["terminal_blockers"][0]["reason"] == (
        "structural-guard-not-accepted"
    )


def test_draw_mixed_accepted_progress_remains_actionable(
    tmp_path: Path,
) -> None:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-mixed-actionable-probes",
    )
    legacy = next(
        row
        for row in candidates
        if row["dimension_id"] == "draw-col-cast-product-local"
    )
    adapted = next(
        row
        for row in candidates
        if str(row["dimension_id"]).startswith("draw-expression-lifetime-")
    )

    payload = classify_source_family_scores(
        [legacy, adapted],
        [
            _draw_score(legacy, accepted=True, actual32=28),
            _draw_score(adapted, accepted=False),
        ],
        context,
    )

    assert payload["status"] == "actionable"
    assert payload["best_candidate"]["candidate_id"] == legacy["candidate_id"]
    assert payload["best_candidate"]["target_matched"] == 1


def test_draw_mixed_rejected_progress_stays_blocked_and_risky(
    tmp_path: Path,
) -> None:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "draw-mixed-risky-probes",
    )
    legacy = next(
        row
        for row in candidates
        if row["dimension_id"] == "draw-col-cast-product-local"
    )
    adapted = next(
        row
        for row in candidates
        if str(row["dimension_id"]).startswith("draw-expression-lifetime-")
    )

    payload = classify_source_family_scores(
        [legacy, adapted],
        [
            _draw_score(legacy, accepted=False, actual32=28),
            _draw_score(adapted, accepted=False),
        ],
        context,
    )

    assert payload["status"] == "blocked"
    assert payload["reason"] == "score-rows-not-terminal-safe"
    assert payload["risky_candidates"][0]["candidate_id"] == legacy["candidate_id"]
    assert payload["risky_candidates"][0]["target_matched"] == 1


def test_draw_adapted_structural_guard_terminal_proof_triage_consumable(
    tmp_path: Path,
) -> None:
    payload = _draw_adapted_structural_guard_terminal_payload(tmp_path)
    artifact = tmp_path / "draw-adapted-terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    function = triaged["functions"][0]
    frontier = next(
        row
        for row in function["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert (
        frontier["kind"] == "post-ceiling-fpr-expression-source-model-synthesis-proof"
    )
    assert frontier["attempted_targets"] == {"32": 28, "37": 26, "46": 26}
    retained = frontier["source_model_proof"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    assert retained
    assert all(row["target_score"] for row in retained)
    assert all(row["structural_guard"] for row in retained)


def test_draw_mixed_source_model_terminal_proof_triage_consumable(
    tmp_path: Path,
) -> None:
    payload = _draw_mixed_legacy_adapted_structural_guard_terminal_payload(tmp_path)
    artifact = tmp_path / "draw-mixed-terminal.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    function = triaged["functions"][0]
    frontier = next(
        row
        for row in function["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert (
        frontier["kind"] == "post-ceiling-fpr-expression-source-model-synthesis-proof"
    )
    assert frontier["attempted_targets"] == {"32": 28, "37": 26, "46": 26}
    retained = frontier["source_model_proof"]["source_family_synthesis"][
        "retained_scored_probes"
    ]
    dimensions = {row["dimension_id"] for row in retained}
    assert "draw-col-cast-product-local" in dimensions
    assert any(
        str(dimension).startswith("draw-expression-lifetime-")
        for dimension in dimensions
    )
    assert all(row["target_score"] for row in retained)
    assert all(row["structural_guard"] for row in retained)
    assert function["meta_ceiling"]["status"] == "terminal-current-source-shape-ceiling"


def test_sort_natural_source_components_survive_terminal_outputs(
    tmp_path: Path,
) -> None:
    context = _context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "natural-probes",
    )
    natural = next(
        row
        for row in candidates
        if str(row["dimension_id"]).startswith("sort-natural-")
    )
    score_row = synthesis._score_row(natural, _score(natural), context)
    compact = synthesis._compact_score_row(score_row)

    assert natural["source_components"]
    assert (
        natural["validation_metadata"]["source_components"]
        == natural["source_components"]
    )
    assert score_row["source_components"] == natural["source_components"]
    assert compact["source_components"] == natural["source_components"]

    payload = classify_source_family_scores(
        candidates,
        [_score(row) for row in candidates],
        context,
    )
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    retained = [
        row
        for row in synthesis_payload["retained_scored_probes"]
        if row["candidate_id"] == natural["candidate_id"]
    ][0]
    source_hunks = [
        row
        for row in synthesis_payload["source_hunks_by_candidate"]
        if row["candidate_id"] == natural["candidate_id"]
    ][0]

    assert retained["source_components"] == natural["source_components"]
    assert source_hunks["source_components"] == natural["source_components"]


def test_sort_semantic_source_components_survive_terminal_outputs(
    tmp_path: Path,
) -> None:
    context = _sort_semantic_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _sort_source(),
            context,
            max_per_dimension=1,
            include_source=True,
        ),
        tmp_path / "semantic-components-probes",
    )
    semantic = next(
        row for row in candidates if row["dimension_id"] in SEMANTIC_SORT_DIMENSIONS
    )
    score_row = synthesis._score_row(semantic, _score(semantic), context)
    compact = synthesis._compact_score_row(score_row)

    assert semantic["source_components"]
    assert (
        semantic["validation_metadata"]["source_components"]
        == semantic["source_components"]
    )
    assert score_row["source_components"] == semantic["source_components"]
    assert compact["source_components"] == semantic["source_components"]

    payload = _sort_semantic_structural_terminal_payload(tmp_path)
    synthesis_payload = payload["source_model_proof"]["source_family_synthesis"]
    retained = [
        row
        for row in synthesis_payload["retained_scored_probes"]
        if row["candidate_id"] == semantic["candidate_id"]
    ][0]
    source_hunks = [
        row
        for row in synthesis_payload["source_hunks_by_candidate"]
        if row["candidate_id"] == semantic["candidate_id"]
    ][0]

    assert retained["source_components"] == semantic["source_components"]
    assert source_hunks["source_components"] == semantic["source_components"]


def _sort_one_hit_classified() -> dict:
    metadata = {
        "function": SORT_FUNCTION,
        "source_function": "mnDiagram_SortNamesByKOs",
        "final_force_phys": {"34": 27, "44": 25},
    }
    return {
        "function": SORT_FUNCTION,
        "source_function": "mnDiagram_SortNamesByKOs",
        "status": "blocked",
        "reason": "score-rows-not-terminal-safe",
        "score_rows": [
            {
                "candidate_id": "post-meta-source-family-sort-init-indexed-write-name-total-locals",
                "dimension_id": "sort-init-indexed-write",
                "target_matched": 1,
                "target_targeted": 2,
                "target_virtual_distance": 1,
                "target_score": {
                    "matched": 1,
                    "targeted": 2,
                    "virtuals": {
                        "34": {"expected": 27, "actual": 27, "matched": True},
                        "44": {"expected": 25, "actual": 31, "matched": False},
                    },
                },
                "structural_guard": {
                    "accepted": False,
                    "normalized_diff_lines": 5,
                    "classification_primary": "signature-type-mismatch",
                },
                "structural_guard_accepted": False,
                "validation_metadata": metadata,
            },
            {
                "candidate_id": "post-meta-source-family-sort-indexed-byte-cache-byte-cache",
                "dimension_id": "sort-indexed-byte-cache",
                "target_matched": 1,
                "target_targeted": 2,
                "target_virtual_distance": 1,
                "target_score": {
                    "matched": 1,
                    "targeted": 2,
                    "virtuals": {
                        "34": {"expected": 27, "actual": None, "matched": False},
                        "44": {"expected": 25, "actual": 25, "matched": True},
                    },
                },
                "structural_guard": {
                    "accepted": False,
                    "normalized_diff_lines": 19,
                    "classification_primary": "inline-boundary-toolchain-artifact",
                },
                "structural_guard_accepted": False,
                "validation_metadata": metadata,
            },
        ],
        "blockers": [{"reason": "structural-guard-not-accepted"}],
    }


def _sort_cross_after_whole_function_classified() -> dict:
    payload = _sort_one_hit_classified()
    payload["output_dir"] = (
        "build/diagnostics/mndiagram_1080_1081_rerun/"
        "sort_cross_after_whole_function"
    )
    payload["next_unsupported_source_family"] = (
        synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    payload["next_unsupported_source_model"] = (
        "stale unbounded-TU data-ownership ceiling"
    )
    payload["context"] = {
        "current_ceiling": {
            "next_unsupported_source_family": (
                synthesis.SORT_UNBOUNDED_TU_DATA_OWNERSHIP_CONTEXT_EXHAUSTED_NEXT_FAMILY
            ),
            "next_unsupported_source_model": (
                "stale unbounded-TU data-ownership ceiling"
            ),
        }
    }
    for row in payload["score_rows"]:
        candidate_id = row["candidate_id"]
        row["source_retained"] = f"build/probes/{candidate_id}.c"
        row["pcdump_path"] = f"build/probes/{candidate_id}.pcdump.txt"
        row["source_hunks"] = [
            {
                "hunk_id": f"{candidate_id}-h001",
                "new_start": 930,
                "new_lines": ["replacement"],
            }
        ]
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


def test_source_family_continuation_terminalizes_sort_cross_after_whole_function_scores() -> None:
    payload = build_source_family_continuation_payload(
        _sort_cross_after_whole_function_classified(),
        [],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal_reason"] != (
        "post-meta-source-family-continuation-needs-more-evidence"
    )
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_MODEL
    )
    proof = payload["source_model_proof"]
    proof_synthesis = proof["source_family_synthesis"]
    assert synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_DIMENSION in {
        row["dimension_id"] for row in proof_synthesis["exhausted_dimensions"]
    }
    assert proof_synthesis["retained_scored_probes"]
    assert proof_synthesis["source_hunks_by_candidate"]


def test_cli_source_family_continuation_uses_sort_cross_after_whole_function_path(
    tmp_path: Path,
) -> None:
    classified = (
        tmp_path
        / "sort_cross_after_whole_function"
        / "source_model_scored.json"
    )
    classified.parent.mkdir(parents=True)
    classified.write_text(
        json.dumps(_sort_cross_after_whole_function_classified()),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "source-family-continuation",
            "--source-model-json",
            str(classified),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "terminal"
    assert payload["next_unsupported_source_family"] == (
        synthesis.SORT_CROSS_TU_SYMBOL_LINKAGE_CONTEXT_EXHAUSTED_NEXT_FAMILY
    )


def _sort_combine_terminal() -> dict:
    return {
        "protected_structural_synthesis": {
            "status": "terminal-component-subset-exhausted",
            "candidate_found": False,
            "required_assignments": {"34": 27, "44": 25},
            "score_coverage": {"ok_combinations": 2, "evaluable_combinations": 2},
            "ranked_candidates": [
                {
                    "candidate_id": "combine-ig34_name_total-low_direct_dst",
                    "parents": ["ig34_name_total", "low_direct_dst"],
                    "path": "combine-ig34_name_total-low_direct_dst.c",
                    "protected_preserved_count": 1,
                    "protected_count": 2,
                    "normalized_diff_lines": 8,
                    "structural_guard": {
                        "accepted": False,
                        "normalized_diff_lines": 8,
                        "opcode_similarity": 0.95,
                    },
                }
            ],
            "terminal_blockers": ["recombine-overlapping-source-hunks"],
            "terminal_blocker": "no-protected-structural-improvement",
        }
    }


def _sort_real_target_score(*, actual34: int | None, actual44: int | None) -> dict:
    matched = int(actual34 == 27) + int(actual44 == 25)
    return {
        "matched": matched,
        "targeted": 2,
        "virtual_distance": 2 - matched,
        "virtuals": {
            "34": {
                "expected": 27,
                "actual": actual34,
                "matched": actual34 == 27,
            },
            "44": {
                "expected": 25,
                "actual": actual44,
                "matched": actual44 == 25,
            },
        },
    }


def _sort_real_score_parent_rows() -> list[dict]:
    return [
        _sort_one_hit_row(
            "post-meta-sort-semantic-owner-dst-local-only",
            "sort-semantic-loop-ownership",
            hit_virtual="34",
            hunk_start=10,
            component_id="sort-loop-ownership",
            source_retained="ig34.c",
        ),
        _sort_one_hit_row(
            "post-meta-sort-semantic-selected-name-after-inner",
            "sort-semantic-selected-name-extraction",
            hit_virtual="44",
            hunk_start=30,
            component_id="sort-selected-name-extraction",
            source_retained="ig44.c",
        ),
    ]


def _sort_raw_semantic_recombine_score(
    candidate_id: str,
    *,
    target_score: dict,
    structural_guard: dict,
    source_retained: str | None = None,
) -> dict:
    row = {
        "pcdump_path": f"build/sort/{candidate_id}.pcdump.txt",
        "target_score": target_score,
        "structural_guard": structural_guard,
    }
    if source_retained is not None:
        row["source_retained"] = source_retained
    return row


def _sort_raw_combine_original_id_parent_rows() -> list[dict]:
    rows = _sort_short_label_real_score_parent_rows()
    rows.append(
        _sort_one_hit_row(
            "post-meta-source-family-sort-indexed-byte-cache-cached-text-inputs",
            "sort-indexed-byte-cache",
            hit_virtual="44",
            hunk_start=60,
            component_id="sort-cached-text-inputs",
            source_retained=(
                "build/diagnostics/mndiagram_1016_rerun/source_model2/sort/"
                "post-meta-source-family-sort-indexed-byte-cache-cached-text-inputs.c"
            ),
        )
    )
    return rows


def _sort_raw_search_combine_real_score_terminal() -> dict:
    init = "post-meta-source-family-sort-init-indexed-write-name-total-locals"
    max_text = "post-meta-source-family-sort-call-return-copy-local-max-text-copy"
    byte_cache = "post-meta-source-family-sort-indexed-byte-cache-byte-cache"
    cached_inputs = "post-meta-source-family-sort-indexed-byte-cache-cached-text-inputs"
    rows = []
    for parent, actual44 in (
        (max_text, 3),
        (byte_cache, 25),
        (cached_inputs, 25),
    ):
        candidate_id = f"combine-{Path(parent).stem}"
        target_score = _sort_real_target_score(actual34=None, actual44=actual44)
        rows.append(
            {
                "status": "ok",
                "candidate_id": candidate_id,
                "parents": [init, parent],
                "path": f"build/sort/{candidate_id}.c",
                "pcdump_path": f"build/sort/{candidate_id}.pcdump.txt",
                "target_score": target_score,
                "target_score_total": 20 + target_score["matched"],
                "protected_preserved_count": target_score["matched"],
                "protected_count": 2,
                "protected_assignments_satisfied": False,
                "missing_protected_assignments": (
                    [{"ig": 34, "phys": 27}]
                    if target_score["matched"]
                    else [{"ig": 34, "phys": 27}, {"ig": 44, "phys": 25}]
                ),
                "satisfied_protected_assignments": (
                    [{"ig": 44, "phys": 25}] if target_score["matched"] else []
                ),
                "structural_guard": {
                    "accepted": False,
                    "status": "protected-loss",
                    "normalized_diff_lines": 20 + target_score["matched"],
                },
                "applied_hunks": [
                    _sort_semantic_hunk(10),
                    _sort_semantic_hunk(30),
                ],
                "score_result": {
                    "parsed_json": {
                        "target_score": target_score,
                        "pcdump_path": f"build/sort/{candidate_id}.pcdump.txt",
                    }
                },
            }
        )
    rows.append(
        {
            "status": "skipped",
            "parents": [max_text, byte_cache],
            "reason": "recombine-overlapping-source-hunks",
        }
    )
    return {
        "kind": "debug-search-combine",
        "function": SORT_FUNCTION,
        "combinations": rows,
    }


def _sort_raw_search_combine_joint_hit() -> dict:
    parents = [
        "post-meta-sort-semantic-owner-dst-local-only",
        "post-meta-sort-semantic-selected-name-after-inner",
    ]
    target_score = _sort_real_target_score(actual34=27, actual44=25)
    return {
        "kind": "debug-search-combine",
        "function": SORT_FUNCTION,
        "combinations": [
            {
                "status": "ok",
                "candidate_id": "combine-joint-hit",
                "parents": parents,
                "path": "build/sort/combine-joint-hit.c",
                "source_retained": "build/sort/combine-joint-hit.c",
                "pcdump_path": "build/sort/combine-joint-hit.pcdump.txt",
                "target_score": target_score,
                "target_score_total": 0,
                "protected_preserved_count": 2,
                "protected_count": 2,
                "protected_assignments_satisfied": True,
                "missing_protected_assignments": [],
                "satisfied_protected_assignments": [
                    {"ig": 34, "phys": 27},
                    {"ig": 44, "phys": 25},
                ],
                "structural_guard": {"accepted": True},
                "applied_hunks": [
                    _sort_semantic_hunk(10),
                    _sort_semantic_hunk(30),
                ],
                "score_result": {
                    "parsed_json": {
                        "target_score": target_score,
                        "source_retained": "build/sort/combine-joint-hit.c",
                        "pcdump_path": "build/sort/combine-joint-hit.pcdump.txt",
                    }
                },
            }
        ],
    }


def _sort_raw_score_source_terminal_payload() -> dict:
    classified = _sort_one_hit_classified_with_rows(_sort_real_score_parent_rows())
    estimate = build_source_family_continuation_payload(classified, [])
    candidate_id = estimate["semantic_recombine"]["ranked_candidates"][0][
        "candidate_id"
    ]
    return build_source_family_continuation_payload(
        classified,
        [
            _sort_raw_semantic_recombine_score(
                candidate_id,
                target_score=_sort_real_target_score(actual34=None, actual44=25),
                structural_guard={
                    "accepted": False,
                    "classification_primary": "inline-boundary-toolchain-artifact",
                },
            )
        ],
    )


def _sort_combine_real_score_protected_loss_terminal(
    *,
    include_repair_seed: bool = True,
) -> dict:
    parents = [
        "post-meta-sort-semantic-selected-name-after-inner",
        "post-meta-sort-semantic-owner-dst-local-only",
    ]
    ranked_candidate = {
        "candidate_id": "combine-selected-name-owner-dst",
        "parents": list(parents),
        "path": "build/sort/combine-selected-name-owner-dst.c",
        "pcdump_path": "build/sort/combine-selected-name-owner-dst.pcdump.txt",
        "target_score": _sort_real_target_score(actual34=None, actual44=25),
        "target_score_total": 24,
        "protected_preserved_count": 1,
        "protected_count": 2,
        "protected_assignments_satisfied": False,
        "missing_protected_assignments": [{"ig": 34, "phys": 27}],
        "satisfied_protected_assignments": [{"ig": 44, "phys": 25}],
        "normalized_diff_lines": 24,
        "structural_guard": {
            "accepted": False,
            "status": "protected-loss",
            "normalized_diff_lines": 24,
            "opcode_similarity": 0.90,
        },
        "source_hunks": [
            _sort_semantic_hunk(10),
            _sort_semantic_hunk(30),
        ],
        "source_components": [
            _sort_semantic_component("sort-loop-ownership"),
            _sort_semantic_component("sort-selected-name-extraction"),
        ],
    }
    repair_seed = {
        "candidate_id": "repair-selected-name-owner-dst",
        "parents": list(parents),
        "path": "build/sort/repair-selected-name-owner-dst.c",
        "source_retained": "build/sort/repair-selected-name-owner-dst.c",
        "pcdump_path": "build/sort/repair-selected-name-owner-dst.pcdump.txt",
        "target_score": _sort_real_target_score(actual34=None, actual44=25),
        "target_score_total": 18,
        "protected_preserved_count": 1,
        "protected_count": 2,
        "protected_assignments_satisfied": False,
        "missing_protected_assignments": [{"ig": 34, "phys": 27}],
        "satisfied_protected_assignments": [{"ig": 44, "phys": 25}],
        "normalized_diff_lines": 12,
        "structural_guard": {
            "accepted": False,
            "status": "lower-drift-protected-loss",
            "normalized_diff_lines": 12,
        },
    }
    worse_repair_seed = {
        **repair_seed,
        "candidate_id": "repair-lost-both",
        "path": "build/sort/repair-lost-both.c",
        "source_retained": "build/sort/repair-lost-both.c",
        "pcdump_path": "build/sort/repair-lost-both.pcdump.txt",
        "target_score": _sort_real_target_score(actual34=None, actual44=3),
        "target_score_total": 32,
        "protected_preserved_count": 0,
        "missing_protected_assignments": [
            {"ig": 34, "phys": 27},
            {"ig": 44, "phys": 25},
        ],
        "satisfied_protected_assignments": [],
        "protected_assignments_satisfied": False,
        "normalized_diff_lines": 16,
    }
    artifact = {
        "combinations": [
            {
                **ranked_candidate,
                "applied_hunks": [
                    _sort_semantic_hunk(10),
                    _sort_semantic_hunk(30),
                ],
                "score_result": {
                    "parsed_json": {
                        "target_score": ranked_candidate["target_score"],
                        "pcdump_path": ranked_candidate["pcdump_path"],
                    }
                },
            }
        ],
        "protected_structural_synthesis": {
            "status": "terminal-component-subset-exhausted",
            "candidate_found": False,
            "required_assignments": {"34": 27, "44": 25},
            "score_coverage": {"ok_combinations": 0, "evaluable_combinations": 1},
            "ranked_candidates": [ranked_candidate],
            "lower_drift_lost_protected_candidates": (
                [repair_seed, worse_repair_seed] if include_repair_seed else []
            ),
            "skipped_pairs": [
                {
                    "parents": list(parents),
                    "reason": "recombine-overlapping-source-hunks",
                }
            ],
            "terminal_blockers": [
                "lower-drift-candidates-lost-protected-assignments",
                "recombine-overlapping-source-hunks",
            ],
            "terminal_blocker": "protected-structural-synthesis-exhausted",
            "next_actions": [
                {
                    "action": "split-overlapping-components",
                    "parents": list(parents),
                },
                {
                    "action": "repair-lower-drift-protected-loss",
                    "candidate_id": repair_seed["candidate_id"],
                },
            ],
        },
    }
    return artifact


def _sort_short_label_real_score_parent_rows() -> list[dict]:
    source_dir = "build/diagnostics/mndiagram_1016_rerun/source_model2/sort"
    rows = [
        _sort_one_hit_row(
            "post-meta-source-family-sort-init-indexed-write-name-total-locals",
            "sort-init-indexed-write",
            hit_virtual="34",
            hunk_start=10,
            component_id="sort-init-region",
            source_retained=(
                f"{source_dir}/post-meta-source-family-sort-init-indexed-write-name-total-locals.c"
            ),
        ),
        _sort_one_hit_row(
            "post-meta-source-family-sort-call-return-copy-local-max-text-copy",
            "sort-call-return-copy-local",
            hit_virtual="44",
            hunk_start=30,
            component_id="sort-max-text-copy",
            source_retained=(
                f"{source_dir}/post-meta-source-family-sort-call-return-copy-local-max-text-copy.c"
            ),
        ),
        _sort_one_hit_row(
            "post-meta-source-family-sort-call-return-copy-local-j-text-copy",
            "sort-call-return-copy-local",
            hit_virtual="44",
            hunk_start=40,
            component_id="sort-j-text-copy",
            source_retained=(
                f"{source_dir}/post-meta-source-family-sort-call-return-copy-local-j-text-copy.c"
            ),
        ),
        _sort_one_hit_row(
            "post-meta-source-family-sort-indexed-byte-cache-byte-cache",
            "sort-indexed-byte-cache",
            hit_virtual="44",
            hunk_start=50,
            component_id="sort-indexed-byte-cache",
            source_retained=(
                f"{source_dir}/post-meta-source-family-sort-indexed-byte-cache-byte-cache.c"
            ),
        ),
    ]
    return rows


def _sort_short_label_combine_real_score_terminal() -> dict:
    source_dir = "build/diagnostics/mndiagram_1016_rerun/source_model2/sort"
    candidates = [
        {
            "candidate_id": "ig34",
            "path": (
                f"{source_dir}/post-meta-source-family-sort-init-indexed-write-name-total-locals.c"
            ),
        },
        {
            "candidate_id": "ig44_max",
            "path": (
                f"{source_dir}/post-meta-source-family-sort-call-return-copy-local-max-text-copy.c"
            ),
        },
        {
            "candidate_id": "ig44_j",
            "path": (
                f"{source_dir}/post-meta-source-family-sort-call-return-copy-local-j-text-copy.c"
            ),
        },
        {
            "candidate_id": "ig44_byte",
            "path": (
                f"{source_dir}/post-meta-source-family-sort-indexed-byte-cache-byte-cache.c"
            ),
        },
    ]
    raw_combinations = []
    ranked = []
    lower_drift = []
    for label, actual44, total in (
        ("ig44_max", 24, 31),
        ("ig44_byte", 25, 20),
        ("ig44_j", 25, 22),
    ):
        candidate_id = f"combine-ig34-{label}"
        parents = ["ig34", label]
        target_score = _sort_real_target_score(actual34=24, actual44=actual44)
        common = {
            "candidate_id": candidate_id,
            "parents": parents,
            "path": f"build/sort/{candidate_id}.c",
            "target_score": target_score,
            "target_score_total": total,
            "protected_preserved_count": target_score["matched"],
            "protected_count": 2,
            "protected_assignments_satisfied": False,
            "missing_protected_assignments": (
                [{"ig": 34, "phys": 27}]
                if target_score["matched"]
                else [{"ig": 34, "phys": 27}, {"ig": 44, "phys": 25}]
            ),
            "satisfied_protected_assignments": (
                [{"ig": 44, "phys": 25}] if target_score["matched"] else []
            ),
            "normalized_diff_lines": total,
            "structural_guard": {
                "accepted": False,
                "status": "protected-loss",
                "normalized_diff_lines": total,
            },
        }
        raw_combinations.append(
            {
                **common,
                "pcdump_path": f"build/sort/{candidate_id}.pcdump.txt",
                "score_result": {
                    "parsed_json": {
                        "target_score": target_score,
                        "pcdump_path": f"build/sort/{candidate_id}.pcdump.txt",
                    }
                },
            }
        )
        ranked.append(
            {
                "candidate_id": candidate_id,
                "parents": parents,
                "structural_guard": common["structural_guard"],
            }
        )
        lower_drift.append(
            {
                **common,
                "source_retained": f"build/sort/lower-drift-{candidate_id}.c",
            }
        )
    return {
        "candidates": candidates,
        "combinations": raw_combinations,
        "protected_structural_synthesis": {
            "status": "terminal-component-subset-exhausted",
            "candidate_found": False,
            "required_assignments": {"34": 27, "44": 25},
            "score_coverage": {"ok_combinations": 0, "evaluable_combinations": 3},
            "ranked_candidates": ranked,
            "lower_drift_lost_protected_candidates": lower_drift,
            "terminal_blockers": [
                "lower-drift-candidates-lost-protected-assignments",
                "protected-structural-synthesis-exhausted",
            ],
            "terminal_blocker": "protected-structural-synthesis-exhausted",
        },
    }


def _sort_select_order_context_artifact() -> dict:
    return {
        "function": SORT_FUNCTION,
        "status": "ok",
        "guard_repair_summary": {"status": "terminal"},
        "terminal_exhaustion_summary": {
            "status": "terminal",
            "terminal_blocker": "select-order-exhausted",
        },
        "target_orders": [],
        "ranking": "ig34hit-name-total-repair",
        "probes": [],
    }


def _sort_manual_subhunk_protected_loss_terminal() -> dict:
    rows = []
    for name, actual44 in (
        ("combine-init-idxbyte-329c6ac916", 27),
        ("combine-init-jtext-9bc60a5737", 27),
        ("combine-init-maxtext-2ea2480b07", 3),
    ):
        parents = name.removeprefix("combine-").rsplit("-", 1)[0].split("-")
        rows.append(
            {
                "candidate_id": name,
                "parents": parents,
                "path": f"build/sort/{name}.c",
                "source_retained": f"build/sort/{name}.c",
                "pcdump_path": f"build/sort/{name}.pcdump.txt",
                "target_score": _sort_real_target_score(
                    actual34=None,
                    actual44=actual44,
                ),
                "target_score_total": 29,
                "protected_preserved_count": 0,
                "protected_count": 2,
                "protected_assignments_satisfied": False,
                "missing_protected_assignments": [
                    {"ig": 34, "phys": 27},
                    {"ig": 44, "phys": 25},
                ],
                "satisfied_protected_assignments": [],
                "normalized_diff_lines": 29,
                "structural_guard": {
                    "accepted": False,
                    "status": "manual-subhunk-protected-loss",
                    "normalized_diff_lines": 29,
                },
                "applied_hunks": [
                    {
                        "parent": parents[0],
                        "kind": "manual-subhunk",
                        "base_lines": [923, 924],
                    },
                    {
                        "parent": parents[-1],
                        "kind": "manual-subhunk",
                        "base_lines": [938, 938],
                    },
                ],
                "score_result": {
                    "parsed_json": {
                        "target_score": _sort_real_target_score(
                            actual34=None,
                            actual44=actual44,
                        ),
                        "pcdump_path": f"build/sort/{name}.pcdump.txt",
                    }
                },
            }
        )
    return {
        "combinations": rows,
        "protected_structural_synthesis": {
            "status": "terminal-component-subset-exhausted",
            "candidate_found": False,
            "required_assignments": {"34": 27, "44": 25},
            "score_coverage": {"ok_combinations": 0, "evaluable_combinations": 3},
            "ranked_candidates": [
                {key: value for key, value in row.items() if key != "applied_hunks"}
                for row in rows
            ],
            "lower_drift_lost_protected_candidates": [
                {key: value for key, value in row.items() if key != "applied_hunks"}
                for row in rows
            ],
            "skipped_pairs": [
                {
                    "parents": ["jtext", "idxbyte"],
                    "reason": "recombine-overlapping-source-hunks",
                }
            ],
            "terminal_blockers": [
                "lower-drift-candidates-lost-protected-assignments",
                "recombine-overlapping-source-hunks",
            ],
            "terminal_blocker": "protected-structural-synthesis-exhausted",
            "next_actions": [
                {"action": "split-overlapping-components"},
                {"action": "repair-lower-drift-protected-loss"},
            ],
        },
    }


def _draw_expression_hit_classified() -> dict:
    metadata = {
        "function": DRAW_FUNCTION,
        "source_function": "mnDiagram_DrawCellNumber",
        "final_force_phys": {"32": 28, "37": 26, "46": 26},
    }
    expression_score = {
        "register_class": "fpr",
        "matched": 1,
        "targeted": 3,
        "virtual_distance": 2,
        "virtuals": {
            "32": {
                "baseline_virtual": 32,
                "expected": 28,
                "status": "missing-expression",
                "candidate_virtual": None,
                "actual": None,
                "matched": False,
                "signature": {
                    "kind": "source-expression",
                    "source_kind": "local",
                    "name": "col_offset",
                    "expression": "y_spacing * (f32) col",
                },
                "baseline_source": {
                    "kind": "local",
                    "name": "col_offset",
                    "expression": "y_spacing * (f32) col",
                },
            },
            "37": {
                "baseline_virtual": 37,
                "expected": 26,
                "status": "ok",
                "candidate_virtual": 37,
                "actual": 28,
                "matched": False,
                "signature": {
                    "kind": "source-expression",
                    "source_kind": "local",
                    "name": "row_offset",
                    "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                },
                "baseline_source": {
                    "kind": "local",
                    "name": "row_offset",
                    "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                },
            },
            "46": {
                "baseline_virtual": 46,
                "expected": 26,
                "status": "ok",
                "candidate_virtual": 32,
                "actual": 26,
                "matched": True,
                "renumbered": True,
                "signature": {
                    "kind": "first-def",
                    "source_kind": "fpr-temp",
                    "opcode": "fsubs",
                    "operands": "<dst>,f45,f44",
                },
                "baseline_source": {
                    "kind": "fpr-temp",
                    "expression": "fsubs f46,f45,f44",
                },
            },
        },
    }
    return {
        "function": DRAW_FUNCTION,
        "source_function": "mnDiagram_DrawCellNumber",
        "status": "actionable",
        "score_rows": [
            {
                "candidate_id": "post-meta-source-family-draw-col-cast-product-local-col-mul-assign",
                "dimension_id": "draw-col-cast-product-local",
                "source_retained": "col-mul-assign.c",
                "target_matched": 0,
                "target_targeted": 3,
                "target_virtual_distance": 3,
                "target_score": {"matched": 0, "targeted": 3, "virtuals": {}},
                "expression_score": expression_score,
                "expression_matched": 1,
                "expression_targeted": 3,
                "expression_virtual_distance": 2,
                "structural_guard": {
                    "accepted": True,
                    "normalized_diff_lines": 0,
                    "opcode_similarity": 1.0,
                },
                "structural_guard_accepted": True,
                "validation_metadata": metadata,
            }
        ],
    }


def _draw_reconcile_generated() -> dict:
    return {
        "class_id": "protected-expression-structural-reconciliation",
        "status": "generated",
        "generated_count": 1,
        "scored_count": 0,
        "candidates": [
            {
                "candidate_id": "reconcile-h001",
                "path": "reconcile-h001.c",
                "preserved_anchor_count": 0,
                "structural_guard_accepted": False,
                "applied_hunks": [{"hunk_id": "h001"}],
            }
        ],
        "generation_blockers": [
            {
                "blocker": "expression-frontier-anchor-not-retained",
                "label": "col_offset",
            },
            {
                "blocker": "expression-frontier-anchor-not-retained",
                "label": "row_offset",
            },
        ],
    }


def _draw_frame_regressing_score() -> dict:
    payload = _draw_expression_hit_classified()["score_rows"][0]
    return {
        **payload,
        "candidate_id": "row-offset-owner-split",
        "source_file": "row-offset-owner-split.c",
        "structural_guard": {
            "accepted": False,
            "normalized_diff_lines": 0,
            "frame_delta": 8,
        },
        "structural_guard_accepted": False,
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "frame": {"size_distance": 8},
            "virtuals": {},
        },
    }


def test_sort_continuation_terminal_ingests_as_retained_frontier(
    tmp_path: Path,
) -> None:
    payload = build_source_family_continuation_payload(
        _sort_one_hit_classified(),
        [_sort_combine_terminal()],
    )

    assert payload["status"] == "terminal"
    assert payload["family_id"] == "post-ceiling-source-model-proof"
    assert payload["terminal"] is True
    assert not payload["accepted_candidates"]
    assert {row["dimension_id"] for row in payload["exhausted_dimensions"]} >= {
        "sort-one-hit-structural-repair",
        "sort-one-hit-recombination",
    }

    artifact = tmp_path / "sort-continuation.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[SORT_FUNCTION],
        artifacts=[artifact],
    )
    frontier = next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert frontier["family_id"] == "post-ceiling-source-model-proof"
    assert (
        frontier["source_model_proof"]["source_family_synthesis"]["evidence_status"]
        == "artifact-synthesis-data"
    )


def test_sort_continuation_without_external_artifacts_has_recombine_blockers() -> None:
    payload = build_source_family_continuation_payload(_sort_one_hit_classified(), [])

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["semantic_recombine"]["status"] == "terminal"
    assert "structural-guard-not-accepted" in payload["terminal_blockers"]
    assert "missing-source-hunks" in payload["terminal_blockers"]
    assert SORT_SEMANTIC_RECOMBINE_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }


def test_draw_continuation_terminal_preserves_renumbered_fsubs_evidence(
    tmp_path: Path,
) -> None:
    payload = build_source_family_continuation_payload(
        _draw_expression_hit_classified(),
        [_draw_reconcile_generated(), _draw_frame_regressing_score()],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert not payload["accepted_candidates"]
    assert "frame-drift" in payload["terminal_blockers"]
    fsubs = next(
        row
        for row in payload["terminal_summary"]["expression_anchors"]
        if row["virtual"] == 46
    )
    assert fsubs["candidate_virtual"] == 32
    assert fsubs["renumbered"] is True
    assert fsubs["actual"] == 26

    artifact = tmp_path / "draw-continuation.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[artifact],
    )
    frontier = next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row["family_id"] == "post-ceiling-source-model-proof"
    )
    assert frontier["family_id"] == "post-ceiling-source-model-proof"
    assert frontier["source_model_proof"]["register_class"] == "fpr"
    assert (
        frontier["source_model_proof"]["source_family_synthesis"]["status"]
        == "synthesis-exhausted"
    )


def test_draw_continuation_plateau_without_route_terminalizes() -> None:
    payload = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [_draw_plateau_continuation_artifact()],
    )

    assert payload["status"] == "terminal"
    assert payload["terminal"] is True
    assert payload["accepted_candidates"] == []
    assert payload["continuation"] is None
    assert payload["terminal_summary"]["status"] == "terminal"
    assert {
        "no-retained-source-route",
        "no-expression-floor-improvement",
    } <= set(payload["terminal_blockers"])


def test_draw_continuation_requires_expression_floor_improvement() -> None:
    plateau = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [
            _draw_plateau_continuation_artifact(
                expression_matched=1,
                source_retained="draw-plateau.c",
            )
        ],
    )

    assert plateau["status"] == "terminal"
    assert plateau["accepted_candidates"] == []
    assert plateau["continuation"] is None
    assert "no-expression-floor-improvement" in plateau["terminal_blockers"]

    improved = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [
            _draw_plateau_continuation_artifact(
                expression_matched=2,
                source_retained="draw-improved.c",
                actual46=26,
            )
        ],
    )

    assert improved["status"] == "actionable"
    assert improved["terminal"] is False
    assert [row["source_retained"] for row in improved["accepted_candidates"]] == [
        "draw-improved.c"
    ]
    assert improved["continuation"]["source_retained"] == "draw-improved.c"


def test_draw_continuation_consumes_suggest_inlines_retained_source_score_rows() -> None:
    payload = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [_draw_helper_boundary_suggest_inlines_retained_source_artifact()],
    )

    assert payload["status"] == "terminal"
    assert "unrecognized-continuation-artifact" not in payload["terminal_blockers"]
    assert (
        payload["continuation_artifacts"][0]["kind"]
        == synthesis.SUGGEST_INLINES_RETAINED_SOURCE_KIND
    )
    assert payload["metrics"]["best_target_matched"] == 1
    assert payload["metrics"]["best_expression_matched"] == 0
    assert (
        synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        in payload["terminal_blockers"]
    )
    assert synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_DIMENSION in {
        row["dimension_id"] for row in payload["exhausted_dimensions"]
    }

    proof = payload["source_model_proof"]
    assert (
        synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
        in proof["closed_families"]
    )
    synthesis_proof = proof["source_family_synthesis"]
    assert (
        synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
        in synthesis_proof["closed_families"]
    )
    assert {
        "block-macro-0001",
        "scalar-return-helper-0001",
    } <= {
        row["candidate_id"]
        for row in synthesis_proof["retained_scored_probes"]
        if row.get("continuation_source")
        == synthesis.SUGGEST_INLINES_RETAINED_SOURCE_KIND
    }


def _write_draw_consumed_source_model_artifacts(
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    context = _draw_context()
    candidates = write_source_family_candidates(
        generate_source_family_candidates(
            _draw_source(),
            context,
            max_per_dimension=4,
            include_source=True,
        ),
        tmp_path / "draw-consumed-source-model-probes",
    )
    row_delta = next(
        row
        for row in candidates
        if row["dimension_id"] == "draw-row-translation-scale-split"
        and row["candidate_id"].endswith("row-delta-local")
    )
    row_delta_id = row_delta["candidate_id"]
    scores = [
        _draw_score(row, actual32=28) if row["candidate_id"] == row_delta_id
        else _draw_score(row)
        for row in candidates
    ]
    source_model_payload = classify_source_family_scores(candidates, scores, context)

    assert source_model_payload["status"] == "actionable"
    assert source_model_payload["best_candidate"]["candidate_id"] == row_delta_id
    assert source_model_payload["best_candidate"]["target_matched"] == 1
    assert source_model_payload["best_candidate"]["expression_matched"] == 0

    source_model_artifact = tmp_path / "draw-source-model-actionable.json"
    source_model_artifact.write_text(
        json.dumps(source_model_payload),
        encoding="utf-8",
    )

    continuation_payload = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [_draw_helper_boundary_suggest_inlines_retained_source_artifact()],
    )
    assert continuation_payload["status"] == "terminal"
    assert continuation_payload["suppression_family"] == (
        "post-ceiling-source-model-proof"
    )
    assert (
        synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
        in continuation_payload["closed_families"]
    )

    continuation_artifact = tmp_path / "draw-helper-boundary-continuation.json"
    continuation_artifact.write_text(
        json.dumps(continuation_payload),
        encoding="utf-8",
    )
    return source_model_artifact, continuation_artifact, row_delta_id


def _draw_suppressed_terminal_frontier(
    triaged: dict,
    candidate_id: str,
) -> dict:
    return next(
        row
        for row in triaged["functions"][0]["terminal_frontiers"]
        if row.get("candidate_id") == candidate_id
        and row.get("suppressed_by_terminal") is True
    )


def _with_different_draw_force(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    different_force = {"32": 29, "37": 26, "46": 26}
    for container in (
        payload,
        payload.get("terminal_summary"),
        payload.get("evidence"),
        payload.get("source_model_proof"),
    ):
        if isinstance(container, dict):
            container["final_force_phys"] = dict(different_force)
            container["attempted_targets"] = dict(different_force)
            container["protected_targets"] = {}
            container["forced_target_map"] = dict(different_force)
    return payload


def test_draw_retained_frontiers_suppresses_consumed_source_model_candidate_after_helper_boundary_continuation(
    tmp_path: Path,
) -> None:
    source_model_artifact, continuation_artifact, row_delta_id = (
        _write_draw_consumed_source_model_artifacts(tmp_path)
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[source_model_artifact, continuation_artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    assert triaged["next_frontier"] is None
    assert triaged["functions"][0]["frontiers"] == []
    assert triaged["functions"][0]["summary"]["suppressed_by_terminal_count"] >= 1

    consumed = _draw_suppressed_terminal_frontier(triaged, row_delta_id)
    assert consumed["family_id"] == "post-ceiling-source-model-proof"
    assert consumed["terminal_reason"] == (
        "post-meta-fpr-expression-hit-continuation-exhausted/"
        "protected-anchor-ceiling"
    )
    assert any(str(continuation_artifact) in path for path in consumed["closed_by"])


def test_draw_retained_frontiers_replay_suppresses_consumed_source_model_candidate_from_aggregate(
    tmp_path: Path,
) -> None:
    source_model_artifact, continuation_artifact, row_delta_id = (
        _write_draw_consumed_source_model_artifacts(tmp_path)
    )
    stale_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[source_model_artifact],
    )
    terminal_payload = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[continuation_artifact],
    )
    stale_frontier = dict(stale_payload["functions"][0]["frontiers"][0])
    stale_frontier.pop("suppression_family", None)
    aggregate = {
        "status": "actionable",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [stale_frontier],
                "terminal_frontiers": (
                    terminal_payload["functions"][0]["terminal_frontiers"]
                ),
                "next_frontier": stale_frontier,
                "summary": {
                    "unexhausted_count": 1,
                    "terminal_count": len(
                        terminal_payload["functions"][0]["terminal_frontiers"]
                    ),
                    "suppressed_by_terminal_count": 0,
                },
            }
        ],
    }
    aggregate_artifact = tmp_path / "draw-retained-frontiers-aggregate.json"
    aggregate_artifact.write_text(json.dumps(aggregate), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[aggregate_artifact],
    )

    assert triaged["status"] == "all-known-frontiers-exhausted"
    assert triaged["next_frontier"] is None
    _draw_suppressed_terminal_frontier(triaged, row_delta_id)


def test_draw_retained_frontiers_keeps_source_model_actionable_when_terminal_force_differs(
    tmp_path: Path,
) -> None:
    source_model_artifact, _, row_delta_id = (
        _write_draw_consumed_source_model_artifacts(tmp_path)
    )
    continuation_payload = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [_draw_helper_boundary_suggest_inlines_retained_source_artifact()],
    )
    continuation_artifact = tmp_path / "draw-different-force-continuation.json"
    continuation_artifact.write_text(
        json.dumps(_with_different_draw_force(continuation_payload)),
        encoding="utf-8",
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[source_model_artifact, continuation_artifact],
    )

    assert triaged["status"] == "actionable"
    assert triaged["next_frontier"]["candidate_id"] == row_delta_id
    assert not any(
        row.get("candidate_id") == row_delta_id
        and row.get("suppressed_by_terminal")
        for row in triaged["functions"][0]["terminal_frontiers"]
    )


def test_draw_retained_frontiers_keeps_source_model_actionable_when_terminal_artifact_is_older(
    tmp_path: Path,
) -> None:
    source_model_artifact, continuation_artifact, row_delta_id = (
        _write_draw_consumed_source_model_artifacts(tmp_path)
    )
    os.utime(continuation_artifact, (100.0, 100.0))
    os.utime(source_model_artifact, (200.0, 200.0))

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[source_model_artifact, continuation_artifact],
    )

    assert triaged["status"] == "actionable"
    assert triaged["next_frontier"]["candidate_id"] == row_delta_id
    assert not any(
        row.get("candidate_id") == row_delta_id
        and row.get("suppressed_by_terminal")
        for row in triaged["functions"][0]["terminal_frontiers"]
    )


def test_draw_continuation_suggest_inlines_expression_progress_stays_actionable() -> None:
    payload = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [
            _draw_helper_boundary_suggest_inlines_retained_source_artifact(
                first_expression_matched=2,
            )
        ],
    )

    assert payload["status"] == "actionable"
    assert payload["continuation"]["source_retained"].endswith("block-macro-0001.c")
    assert (
        synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
        not in payload["terminal_blockers"]
    )
    assert (
        synthesis.DRAW_COUPLED_FPR_HELPER_BOUNDARY_HANDOFF_FAMILY
        not in payload["closed_families"]
    )


def test_cli_source_family_continuation_accepts_suggest_inlines_score_rows_artifact(
    tmp_path: Path,
) -> None:
    classified = tmp_path / "classified.json"
    artifact = tmp_path / "suggest-inlines-retained-source.json"
    classified.write_text(json.dumps(_draw_floor_summary_classified()), encoding="utf-8")
    artifact.write_text(
        json.dumps(_draw_helper_boundary_suggest_inlines_retained_source_artifact()),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "source-family-continuation",
            "--source-model-json",
            str(classified),
            "--artifact",
            str(artifact),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "unrecognized-continuation-artifact" not in payload["terminal_blockers"]
    assert (
        payload["continuation_artifacts"][0]["kind"]
        == synthesis.SUGGEST_INLINES_RETAINED_SOURCE_KIND
    )


def test_draw_terminal_proof_names_coupled_expression_class() -> None:
    payload = build_source_family_continuation_payload(
        _draw_floor_summary_classified(),
        [_draw_plateau_continuation_artifact()],
    )

    proof = payload["source_model_proof"]
    assert (
        proof["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS
    )
    assert (
        payload["unsupported_source_expression_class"] == DRAW_COUPLED_UNSUPPORTED_CLASS
    )
    assert proof["next_unsupported_source_model"] == DRAW_COUPLED_UNSUPPORTED_MODEL
    assert payload["next_unsupported_source_model"] == DRAW_COUPLED_UNSUPPORTED_MODEL
    anchors = {row["virtual"]: row for row in proof["expression_anchors"]}
    assert set(anchors) == {32, 37, 46}
    assert anchors[32]["baseline_source"]["source_file"] == "src/melee/mn/mndiagram.c"
    assert anchors[37]["baseline_source"]["name"] == "row_offset"
    assert anchors[46]["baseline_source"]["expression"] == "fsubs f46,f45,f44"


def test_cli_writes_probes_from_meta_ceiling_fixture(tmp_path: Path) -> None:
    meta = tmp_path / "meta.json"
    source = tmp_path / "sort.c"
    out_dir = tmp_path / "out"
    meta.write_text(json.dumps(_meta_payload()), encoding="utf-8")
    source.write_text(_sort_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] > 4
    assert {row["dimension_id"] for row in payload["candidates"]} >= {
        "sort-init-indexed-write",
        "sort-swap-slot-lvalue",
    }
    assert all(Path(row["candidate_path"]).is_file() for row in payload["candidates"])


def test_cli_source_function_override_allows_public_sort_alias(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "meta.json"
    source = tmp_path / "sort.c"
    out_dir = tmp_path / "out"
    source_function = "mnDiagram_SortNamesByKOs"
    meta.write_text(json.dumps(_meta_payload()), encoding="utf-8")
    source.write_text(
        _sort_source().replace("mnDiagram_8023FC28", source_function),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            SORT_FUNCTION,
            "--source-function",
            source_function,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["context"]["source_function"] == source_function
    assert payload["candidate_count"] > 4
    first_candidate = Path(payload["candidates"][0]["candidate_path"]).read_text()
    assert f"void {source_function}(void)" in first_candidate


def test_cli_writes_draw_probes_from_meta_ceiling_fixture(tmp_path: Path) -> None:
    meta = tmp_path / "draw-meta.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-out"
    meta.write_text(json.dumps(_draw_meta_payload()), encoding="utf-8")
    source.write_text(_draw_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["context"]["register_class"] == "fpr"
    assert payload["candidate_count"] > 3
    assert {row["dimension_id"] for row in payload["candidates"]} >= {
        "draw-col-cast-product-local",
        "draw-digit-callarg-fsubs-temp",
    }
    assert all(Path(row["candidate_path"]).is_file() for row in payload["candidates"])


def test_cli_source_model_synthesis_writes_draw_alternate_probes(
    tmp_path: Path,
) -> None:
    context = _draw_alternate_context()
    meta = tmp_path / "draw-alternate-meta.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-alternate-out"
    meta.write_text(
        json.dumps(
            {
                "function": DRAW_FUNCTION,
                "current_ceiling": context.current_ceiling,
            }
        ),
        encoding="utf-8",
    )
    source.write_text(_draw_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    alternate = [
        row
        for row in payload["candidates"]
        if row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
    ]
    assert len(alternate) == 8
    assert {row["dimension_id"] for row in payload["candidates"]} == {
        DRAW_ALTERNATE_DIMENSION
    }
    assert all(row["source_hunks"] for row in alternate)
    assert all(row["source_components"] for row in alternate)
    assert all(Path(row["candidate_path"]).is_file() for row in alternate)


def test_cli_source_model_synthesis_writes_draw_alternate_split_source_probes(
    tmp_path: Path,
) -> None:
    context = _draw_alternate_context()
    meta = tmp_path / "draw-alternate-split-meta.json"
    source = tmp_path / "draw-split.c"
    out_dir = tmp_path / "draw-alternate-split-out"
    meta.write_text(
        json.dumps(
            {
                "function": DRAW_FUNCTION,
                "current_ceiling": context.current_ceiling,
            }
        ),
        encoding="utf-8",
    )
    source.write_text(_draw_split_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    alternate = [
        row
        for row in payload["candidates"]
        if row["dimension_id"] == DRAW_ALTERNATE_DIMENSION
    ]
    assert len(alternate) == 8
    assert {row["candidate_id"] for row in alternate} == DRAW_ALTERNATE_CANDIDATE_IDS
    assert {row["dimension_id"] for row in payload["candidates"]} == {
        DRAW_ALTERNATE_DIMENSION
    }
    assert all(row["source_hunks"] for row in alternate)
    assert all(row["source_components"] for row in alternate)
    assert all(Path(row["candidate_path"]).is_file() for row in alternate)


def test_cli_source_model_synthesis_draw_expression_lifetime_writes_adapted_probes(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "draw-meta.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-expression-out"
    meta.write_text(json.dumps(_draw_meta_payload()), encoding="utf-8")
    source.write_text(_draw_source(), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["candidate_count"] > 10
    assert {row["dimension_id"] for row in payload["candidates"]} >= {
        "draw-expression-lifetime-product-operand-ownership"
    }
    assert {row["candidate_id"] for row in payload["candidates"]} >= {
        "product-col-cast-owner-materialize",
        "product-col-offset-sink-owner",
        "digit-guard-product-before-count",
    }
    assert any(
        "product-col-cast-owner-materialize" in row["candidate_path"]
        for row in payload["candidates"]
    )
    assert all(Path(row["candidate_path"]).is_file() for row in payload["candidates"])


def test_cli_source_model_synthesis_live_score_interrupt_emits_partial_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    meta = tmp_path / "draw-meta.json"
    source = tmp_path / "draw.c"
    target = tmp_path / "draw-target.json"
    out_dir = tmp_path / "draw-score-out"
    meta.write_text(json.dumps(_draw_meta_payload()), encoding="utf-8")
    source.write_text(_draw_source(), encoding="utf-8")
    target.write_text("{}", encoding="utf-8")
    calls = 0

    def fake_run(cmd, *, cwd, env, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "target_score": {"matched": 0, "targeted": 3},
                    "expression_score": {"matched": 0, "targeted": 3},
                    "structural_guard": {"accepted": True},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--target",
            str(target),
            "--cflags-from",
            str(source),
            "--write-probes",
            str(out_dir),
            "--max-per-dimension",
            "1",
            "--score",
            "--timeout",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 130, result.output
    payload = json.loads(result.output)
    assert calls == 2
    assert payload["status"] == "incomplete"
    assert payload["score_mode"] == "live-partial"
    assert payload["partial"] is True
    assert payload["interrupted"] is True
    assert payload["terminal_blocker"] == "score-source-keyboard-interrupt"
    assert payload["partial_score"]["reason"] == "live-score-interrupted"
    assert payload["interruption"]["exit_code"] == 130
    assert payload["partial_score"]["last_candidate_id"]
    assert (
        payload["last_candidate"]["candidate_id"]
        == payload["partial_score"]["last_candidate_id"]
    )
    assert payload["score_rows"]
    assert any(
        row["score_error"] == "score-source-interrupted"
        for row in payload["score_rows"]
    )
    assert payload["missing_score_candidate_ids"]
    assert payload["output_dir"] == str(out_dir.resolve())


def test_cli_source_model_synthesis_live_score_timeout_emits_partial_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    meta = tmp_path / "draw-meta.json"
    source = tmp_path / "draw.c"
    target = tmp_path / "draw-target.json"
    out_dir = tmp_path / "draw-timeout-out"
    meta.write_text(json.dumps(_draw_meta_payload()), encoding="utf-8")
    source.write_text(_draw_source(), encoding="utf-8")
    target.write_text("{}", encoding="utf-8")

    def fake_run(cmd, *, cwd, env, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd,
            timeout=7.0,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(synthesis.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--target",
            str(target),
            "--cflags-from",
            str(source),
            "--write-probes",
            str(out_dir),
            "--max-per-dimension",
            "1",
            "--score",
            "--timeout",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 124, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "incomplete"
    assert payload["score_mode"] == "live-partial"
    assert payload["terminal_blocker"] == "score-source-timeout"
    assert payload["interruption"]["timeout_seconds"] == 7.0
    assert any(
        row["score_error"] == "score-source-timeout" and row["score_returncode"] == 124
        for row in payload["score_rows"]
    )
    assert payload["output_dir"] == str(out_dir.resolve())


def test_cli_source_function_override_allows_public_draw_alias(
    tmp_path: Path,
) -> None:
    meta = tmp_path / "draw-meta.json"
    source = tmp_path / "draw.c"
    out_dir = tmp_path / "draw-out"
    source_function = "mnDiagram_DrawCellNumber"
    meta.write_text(json.dumps(_draw_meta_payload()), encoding="utf-8")
    source.write_text(
        _draw_source().replace("mnDiagram_80241E78", source_function),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "source-model-synthesis",
            "--function",
            DRAW_FUNCTION,
            "--source-function",
            source_function,
            "--meta-ceiling-json",
            str(meta),
            "--source-file",
            str(source),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["context"]["source_function"] == source_function
    assert payload["context"]["register_class"] == "fpr"
    assert payload["candidate_count"] > 3
    first_candidate = Path(payload["candidates"][0]["candidate_path"]).read_text()
    assert (
        f"void {source_function}(void* arg0, u8 arg1, u8 arg2, int arg3)"
        in first_candidate
    )
