import json

from typer.testing import CliRunner

from src.cli import app as cli_app
from src.cli import debug as cli_debug
from src.mwcc_debug.allocator_ceiling import (
    classify_allocator_ceiling,
    render_allocator_ceiling_text,
)
from src.mwcc_debug.post_source_context_discovery import (
    DISCOVERY_KIND,
    DRAW_FUNCTION,
    DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
    DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY,
    DRAW_POST_SOURCE_CONTEXT_DIMENSION,
    DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY,
    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
    DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY,
    DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL,
    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY,
    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL,
    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER,
    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON,
    DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION,
    DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY,
    DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL,
    DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON,
    DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
    DRAW_HELPER_BOUNDARY_FINAL_MODEL,
    DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY,
    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL,
    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
    DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
    PostSourceContextFprCeilingNextDimensionDiscovery,
)
from src.mwcc_debug.retained_frontier_triage import triage_retained_frontiers
from src.search.cli import search_app


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
DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff"
)


def _score_row(**overrides):
    row = {
        "candidate_id": "draw-post-alt-source-context-loop-digit-jobj-local",
        "dimension_id": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
        "source_retained": "build/diagnostics/draw/source-context.c",
        "pcdump_path": "build/diagnostics/draw/source-context.pcdump.txt",
        "target_matched": 0,
        "target_targeted": 3,
        "target_score": {
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 26, "matched": False},
                "37": {"expected": 26, "actual": 28, "matched": False},
                "46": {"expected": 26, "actual": None, "matched": False},
            },
        },
        "expression_matched": 1,
        "expression_targeted": 3,
        "expression_score": {
            "register_class": "fpr",
            "matched": 1,
            "targeted": 3,
            "virtual_distance": 2,
            "renumbered": 0,
            "false_positive_virtual_id_hit_count": 0,
            "virtuals": {
                "37": {"expected": 26, "actual": 28, "matched": False},
                "46": {"expected": 26, "actual": 26, "matched": True},
            },
        },
        "source_hunks": [
            {
                "hunk_id": "post-meta-loop-digit-jobj-local-h001",
                "old_start": 2574,
                "old_end": 2576,
                "new_start": 2575,
                "new_end": 2576,
                "old_lines": ["HSD_JObjAddAnimAll(jobj, ...);"],
                "new_lines": ["HSD_JObjAddAnimAll(digit_jobj, ...);"],
            }
        ],
        "source_components": [{"component_id": "loop-digit-jobj-local"}],
        "wrong_registers": [{"virtual": 32, "expected": 28, "actual": 26}],
        "expression_wrong_registers": [
            {"virtual": 37, "expected": 26, "actual": 28}
        ],
        "structural_guard": {
            "accepted": True,
            "shape_preserved": True,
            "normalized_diff_lines": 0,
            "opcode_similarity": 1.0,
            "frame_delta": 0,
        },
        "normalized_diff_lines": 0,
        "opcode_similarity": 1.0,
        "frame_delta": 0,
    }
    row.update(overrides)
    return row


def _whole_function_score_row(**overrides):
    row = {
        "candidate_id": (
            "draw-post-source-context-whole-function-"
            "joint-data-owner-with-loop-object"
        ),
        "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        "source_retained": "build/diagnostics/draw/whole-function.c",
        "pcdump_path": "build/diagnostics/draw/whole-function.pcdump.txt",
        "target_matched": 1,
        "target_targeted": 3,
        "target_score": {
            "matched": 1,
            "targeted": 3,
            "virtual_distance": 2,
            "virtuals": {
                "32": {"expected": 28, "actual": 26, "matched": False},
                "37": {"expected": 26, "actual": 28, "matched": False},
                "46": {"expected": 26, "actual": 26, "matched": True},
            },
        },
        "expression_matched": 1,
        "expression_targeted": 3,
        "expression_score": {
            "register_class": "fpr",
            "matched": 1,
            "targeted": 3,
            "virtual_distance": 2,
            "renumbered": 0,
            "false_positive_virtual_id_hit_count": 0,
            "virtuals": {
                "37": {"expected": 26, "actual": 28, "matched": False},
                "46": {"expected": 26, "actual": 26, "matched": True},
            },
        },
        "source_hunks": [
            {
                "hunk_id": "whole-function-joint-data-owner-h001",
                "old_start": 2548,
                "old_end": 2594,
                "new_start": 2548,
                "new_end": 2598,
                "old_lines": ["HSD_JObjLoadJoint(joint_data->joint);"],
                "new_lines": ["digit_joint = joint_data->joint;"],
            }
        ],
        "source_components": [
            {"component_id": "whole-function-preloop-object-owner"},
            {"component_id": "whole-function-loop-joint-data-owner"},
        ],
        "structural_guard": {
            "accepted": False,
            "shape_preserved": False,
            "normalized_diff_lines": 11,
            "opcode_similarity": 0.955684,
            "frame_delta": 0,
            "reject_reason": "inline-boundary-toolchain-artifact",
        },
        "normalized_diff_lines": 11,
        "opcode_similarity": 0.955684,
        "frame_delta": 0,
    }
    row.update(overrides)
    return row


def _helper_boundary_score_row(**overrides):
    row = {
        "candidate_id": "block-macro-0001",
        "dimension_id": "inline-local-write-helper-block-macro",
        "source_retained": "build/diagnostics/draw/helper-boundary.c",
        "pcdump_path": "build/diagnostics/draw/helper-boundary.pcdump.txt",
        "target_matched": 1,
        "target_targeted": 3,
        "target_score": {
            "matched": 1,
            "targeted": 3,
            "virtual_distance": 2,
            "virtuals": {
                "32": {"expected": 28, "actual": 28, "matched": True},
                "37": {"expected": 26, "actual": 27, "matched": False},
                "46": {"expected": 26, "actual": 2, "matched": False},
            },
        },
        "expression_matched": 0,
        "expression_targeted": 3,
        "expression_score": {
            "register_class": "fpr",
            "matched": 0,
            "targeted": 3,
            "virtual_distance": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": None, "matched": False},
                "37": {"expected": 26, "actual": None, "matched": False},
                "46": {"expected": 26, "actual": None, "matched": False},
            },
        },
        "source_hunks": [
            {
                "hunk_id": "helper-boundary-h001",
                "old_start": 2562,
                "old_end": 2578,
                "new_start": 2562,
                "new_end": 2578,
                "old_lines": ["row_offset = HSD_JObjGetTranslationY(jobj2) - base;"],
                "new_lines": ["MN_DRAW_HELPER_BOUNDARY(row_offset);"],
            }
        ],
        "structural_guard": {
            "accepted": True,
            "classification_primary": "normalized-structural-match",
            "normalized_diff_lines": 0,
        },
        "normalized_diff_lines": 0,
    }
    row.update(overrides)
    return row


def _source_model(row=None):
    row = row or _score_row()
    return {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "terminal_reason": (
            "draw-loop-body-callsite-and-object-base-lifetime-source-context-"
            "exhausted/no-floor-improvement"
        ),
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "attempted_equivalence_classes": [
            "draw-alternate-fpr-expression-structure",
            DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
        ],
        "next_unsupported_source_family": (
            DRAW_POST_ALTERNATE_SOURCE_CONTEXT_FINAL_FAMILY
        ),
        "next_unsupported_source_model": "old #1035 final source-context sentinel",
        "next_unsupported_source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2561,
                "name": "row_offset",
                "dimension_id": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
            },
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2574,
                "name": "loop digit jobj",
                "dimension_id": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
            },
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2591,
                "name": "add child",
                "dimension_id": DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
            },
        ],
    }


def _whole_function_source_model(row=None):
    row = row or _whole_function_score_row()
    return {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "terminal_reason": (
            "draw-post-source-context-whole-function-fpr-source-model-"
            "exhausted/no-floor-improvement"
        ),
        "candidate_count": 6,
        "score_count": 6,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "attempted_equivalence_classes": [
            DRAW_POST_ALTERNATE_SOURCE_CONTEXT_DIMENSION,
            DRAW_POST_SOURCE_CONTEXT_DIMENSION,
        ],
        "exhausted_dimensions": [
            {
                "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
                "status": "scored-terminal",
                "candidate_count": 6,
                "score_count": 6,
            }
        ],
        "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
        "unsupported_source_expression_class": DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS,
        "unsupported_source_expression_model": DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL,
        "next_unsupported_source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2548,
                "name": "whole function Draw ownership",
                "dimension_id": DRAW_POST_SOURCE_CONTEXT_DIMENSION,
            }
        ],
    }


def _stack_clean_score_row(**overrides):
    row = _whole_function_score_row(
        candidate_id="draw-stack-clean-final-row",
        dimension_id=DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        source_retained="build/diagnostics/draw/stack-clean-final.c",
        pcdump_path="build/diagnostics/draw/stack-clean-final.pcdump.txt",
        source_hunks=[{"hunk_id": "stack-clean-final-h001"}],
    )
    row.update(overrides)
    return row


def _stack_clean_final_source_model(row=None):
    row = row or _stack_clean_score_row()
    evidence = {
        "seed_candidate_id": "draw-stack-clean-final-row",
        "source_retained": row["source_retained"],
        "pcdump_path": row["pcdump_path"],
        "source_hunks": row["source_hunks"],
        "stack_frame_facts": {"frame_delta": 8},
    }
    exhausted = [
        {
            "dimension_id": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        }
    ]
    return {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "attempted_equivalence_classes": [
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ],
        "exhausted_source_dimension": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION,
        "exhausted_dimensions": exhausted,
        "next_unsupported_source_family": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
        ),
        "next_unsupported_source_dimension": (
            DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        ),
        "stack_clean_no_anchor_evidence": evidence,
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "attempted_equivalence_classes": [
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ],
            "exhausted_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "exhausted_dimensions": exhausted,
            "terminal_blocker": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_BLOCKER,
            "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
            "next_unsupported_source_family": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
            ),
            "next_unsupported_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "stack_clean_no_anchor_evidence": evidence,
        },
    }


def _loop_callsite_score_row(**overrides):
    row = _stack_clean_score_row(
        candidate_id="draw-post-stack-loop-callsite-loop-digit-jobj-owner",
        dimension_id=DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
        source_retained="build/diagnostics/draw/loop-callsite-final.c",
        pcdump_path="build/diagnostics/draw/loop-callsite-final.pcdump.txt",
        source_hunks=[{"hunk_id": "loop-callsite-final-h001"}],
    )
    row.update(overrides)
    return row


def _loop_callsite_final_source_model(row=None):
    row = row or _loop_callsite_score_row()
    return {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "terminal_reason": DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON,
        "terminal_blocker": DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "attempted_equivalence_classes": [
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        ],
        "exhausted_source_dimension": (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        ),
        "exhausted_dimensions": [
            {
                "dimension_id": DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
                "status": "scored-terminal",
                "exhaustion_reason": (
                    DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
                ),
            }
        ],
        "next_unsupported_source_family": (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
        ),
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "attempted_equivalence_classes": [
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            ],
            "exhausted_source_dimension": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
            ),
            "exhausted_dimensions": [
                {
                    "dimension_id": DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION,
                    "status": "scored-terminal",
                    "exhaustion_reason": (
                        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
                    ),
                }
            ],
            "terminal_blocker": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_BLOCKER
            ),
            "terminal_reason": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
            ),
            "next_unsupported_source_family": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
            ),
            "next_unsupported_source_model": (
                DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
            ),
            "retained_scored_probes": [row],
        },
    }


def _protected_reconcile_score_row(**overrides):
    row = _stack_clean_score_row(
        candidate_id="draw-protected-reconcile-row-delta-retained",
        dimension_id="draw-row-translation-scale-split",
        source_retained="build/diagnostics/draw/protected-reconcile-final.c",
        pcdump_path=(
            "build/diagnostics/draw/protected-reconcile-final.pcdump.txt"
        ),
        source_hunks=[
            {
                "hunk_id": "protected-reconcile-row-delta-h001",
                "old_start": 2561,
                "old_end": 2563,
                "new_start": 2561,
                "new_end": 2563,
                "old_lines": ["row_offset = ...;"],
                "new_lines": ["row_offset_adj = ...;"],
            }
        ],
    )
    row.update(overrides)
    return row


def _protected_reconcile_terminal_proof(row=None):
    row = row or _protected_reconcile_score_row()
    exhausted = [
        {
            "dimension_id": DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": (
                DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
            ),
        }
    ]
    synthesis = {
        "status": "synthesis-exhausted",
        "attempted_equivalence_classes": [
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
        ],
        "exhausted_source_dimension": (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
        ),
        "exhausted_dimensions": exhausted,
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
        "retained_scored_probes": [row],
    }
    return {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "terminal_reason": (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
        ),
        "terminal_blocker": (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
        ),
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "attempted_equivalence_classes": [
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
        ],
        "exhausted_source_dimension": (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
        ),
        "exhausted_dimensions": exhausted,
        "next_unsupported_source_family": (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
        ),
        "next_unsupported_source_model": (
            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
        ),
        "next_unsupported_source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2561,
                "name": "protected expression reconcile",
                "dimension_id": (
                    DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
                ),
            }
        ],
        "source_family_synthesis": synthesis,
    }


def _protected_reconcile_artifacts_with_stale_loop_history(row=None):
    proof = _protected_reconcile_terminal_proof(row)
    stale_loop = _loop_callsite_final_source_model()
    source_model = {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "context": {
            "current_ceiling": proof,
            "retained_frontier_history": {
                "stale_terminal": stale_loop,
            },
        },
    }
    retained = {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [],
                "next_frontier": None,
                "summary": {"terminal_count": 1, "unexhausted_count": 0},
                "meta_ceiling": {
                    "kind": "retained-frontiers-meta-ceiling",
                    "function": DRAW_FUNCTION,
                    "status": "terminal-current-source-shape-ceiling",
                    "terminal_proof": proof,
                    "allocator_history": {
                        "stale_terminal": stale_loop,
                    },
                },
            }
        ],
        "meta_ceiling": {
            "kind": "retained-frontiers-meta-ceiling",
            "function": DRAW_FUNCTION,
            "status": "terminal-current-source-shape-ceiling",
            "terminal_proof": proof,
        },
        "next_frontier": None,
    }
    allocator = {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        ),
        "current_ceiling": proof,
        "post_source_context_next_dimension": proof,
        "retained_frontiers_meta_ceiling": {
            "kind": "retained-frontiers-meta-ceiling",
            "function": DRAW_FUNCTION,
            "status": "terminal-current-source-shape-ceiling",
            "terminal_proof": proof,
            "retained_history": {
                "stale_terminal": stale_loop,
            },
        },
    }
    return source_model, retained, allocator


def _discover_protected_reconcile(row=None):
    source_model, retained, allocator = (
        _protected_reconcile_artifacts_with_stale_loop_history(row)
    )
    return PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
        retained_frontiers=retained,
        allocator_ceiling=allocator,
    )


def _helper_boundary_terminal_proof(row=None):
    row = row or _helper_boundary_score_row()
    exhausted = [
        {
            "dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "status": "scored-terminal",
            "exhaustion_reason": DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
        }
    ]
    synthesis = {
        "status": "terminal",
        "terminal_reason": DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
        "terminal_blocker": DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
        "attempted_equivalence_classes": [DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION],
        "exhausted_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "exhausted_dimensions": exhausted,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_HELPER_BOUNDARY_FINAL_MODEL,
    }
    return {
        "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "terminal_reason": DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
        "terminal_blocker": DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON,
        "candidate_scores": [row],
        "retained_scored_probes": [row],
        "attempted_equivalence_classes": [DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION],
        "exhausted_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "exhausted_dimensions": exhausted,
        "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
        "next_unsupported_source_model": DRAW_HELPER_BOUNDARY_FINAL_MODEL,
        "next_unsupported_source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2562,
                "name": "helper-boundary expression lifetime",
                "dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            }
        ],
        "source_family_synthesis": synthesis,
    }


def _helper_boundary_artifacts_with_stale_protected_reconcile(row=None):
    proof = _helper_boundary_terminal_proof(row)
    stale_protected = _protected_reconcile_terminal_proof()
    source_model = {
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "status": "terminal",
        "function": DRAW_FUNCTION,
        "context": {
            "current_ceiling": proof,
            "retained_frontier_history": {
                "stale_protected_reconcile": stale_protected,
            },
        },
    }
    retained = {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [
                    {
                        "function": DRAW_FUNCTION,
                        "frontier_id": "draw-helper-boundary-terminal",
                        "family_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
                        "kind": (
                            "draw-coupled-fpr-expression-lifetime-"
                            "helper-boundary-terminal"
                        ),
                        "terminal": True,
                        "terminal_reason": (
                            DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
                        ),
                        "source_model_proof": proof,
                    },
                    {
                        "function": DRAW_FUNCTION,
                        "frontier_id": "stale-protected-reconcile",
                        "family_id": DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION,
                        "terminal": True,
                        "terminal_reason": (
                            DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
                        ),
                        "source_model_proof": stale_protected,
                    },
                ],
                "next_frontier": None,
                "summary": {"terminal_count": 2, "unexhausted_count": 0},
                "meta_ceiling": {
                    "kind": "retained-frontiers-meta-ceiling",
                    "function": DRAW_FUNCTION,
                    "status": "terminal-current-source-shape-ceiling",
                    "terminal_proof": proof,
                },
            }
        ],
        "meta_ceiling": {
            "kind": "retained-frontiers-meta-ceiling",
            "function": DRAW_FUNCTION,
            "status": "terminal-current-source-shape-ceiling",
            "terminal_proof": proof,
        },
        "next_frontier": None,
    }
    allocator = {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        ),
        "current_ceiling": proof,
        "retained_frontiers_meta_ceiling": {
            "kind": "retained-frontiers-meta-ceiling",
            "function": DRAW_FUNCTION,
            "status": "terminal-current-source-shape-ceiling",
            "terminal_proof": proof,
        },
    }
    return source_model, retained, allocator


def _discover_helper_boundary_with_stale_protected(row=None):
    source_model, retained, allocator = (
        _helper_boundary_artifacts_with_stale_protected_reconcile(row)
    )
    return PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
        retained_frontiers=retained,
        allocator_ceiling=allocator,
    )


def _retained_frontiers_terminal(source_model=None):
    source_model = source_model or _source_model()
    proof = {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "candidate_scores": source_model["candidate_scores"],
        "retained_scored_probes": source_model["retained_scored_probes"],
        "attempted_equivalence_classes": source_model["attempted_equivalence_classes"],
        "next_unsupported_source_family": source_model[
            "next_unsupported_source_family"
        ],
        "next_unsupported_source_model": source_model[
            "next_unsupported_source_model"
        ],
        "next_unsupported_source_spans": source_model[
            "next_unsupported_source_spans"
        ],
    }
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [
                    {
                        "function": DRAW_FUNCTION,
                        "frontier_id": "draw-old-source-context-terminal",
                        "family_id": "post-ceiling-source-model-proof",
                        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
                        "terminal": True,
                        "terminal_reason": (
                            "post-ceiling-fpr-expression-source-model-"
                            "synthesis-exhausted"
                        ),
                        "source_model_proof": proof,
                    }
                ],
                "next_frontier": None,
                "summary": {"terminal_count": 1, "unexhausted_count": 0},
            }
        ],
        "next_frontier": None,
    }


def _retained_frontiers_after_whole_function(source_model=None):
    source_model = source_model or _whole_function_source_model()
    proof = {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "candidate_scores": source_model["candidate_scores"],
        "retained_scored_probes": source_model["retained_scored_probes"],
        "attempted_equivalence_classes": source_model["attempted_equivalence_classes"],
        "exhausted_dimensions": source_model["exhausted_dimensions"],
        "next_unsupported_source_family": source_model[
            "next_unsupported_source_family"
        ],
        "next_unsupported_source_model": source_model[
            "next_unsupported_source_model"
        ],
        "unsupported_source_expression_class": source_model[
            "unsupported_source_expression_class"
        ],
        "unsupported_source_expression_model": source_model[
            "unsupported_source_expression_model"
        ],
        "next_unsupported_source_spans": source_model[
            "next_unsupported_source_spans"
        ],
    }
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [
                    {
                        "function": DRAW_FUNCTION,
                        "frontier_id": "draw-post-whole-function-terminal",
                        "family_id": "post-ceiling-source-model-proof",
                        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
                        "terminal": True,
                        "terminal_reason": (
                            "post-ceiling-fpr-expression-source-model-"
                            "synthesis-exhausted"
                        ),
                        "source_model_proof": proof,
                    }
                ],
                "next_frontier": None,
                "summary": {"terminal_count": 1, "unexhausted_count": 0},
                "meta_ceiling": {
                    "kind": "retained-frontiers-meta-ceiling",
                    "function": DRAW_FUNCTION,
                    "status": "terminal-current-source-shape-ceiling",
                    "terminal_proof": proof,
                },
            }
        ],
        "next_frontier": None,
    }


def _retained_frontiers_after_stack_clean_final(source_model=None):
    source_model = source_model or _stack_clean_final_source_model()
    helper_terminal = {
        "function": DRAW_FUNCTION,
        "frontier_id": "draw-helper-boundary-terminal",
        "family_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "suppression_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
        "kind": "draw-coupled-fpr-expression-lifetime-helper-boundary-terminal",
        "terminal": True,
        "terminal_reason": "all-inline-helper-candidates-rejected",
        "source_model_proof": {
            "next_unsupported_source_dimension": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION,
            "next_unsupported_source_model": DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL,
            "source_family_synthesis": {
                "exhausted_dimensions": [
                    {"dimension_id": DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION}
                ],
            },
        },
    }
    stack_terminal = {
        "function": DRAW_FUNCTION,
        "frontier_id": "draw-stack-clean-final-terminal",
        "family_id": "post-ceiling-source-model-proof",
        "kind": "post-ceiling-fpr-expression-source-model-synthesis-proof",
        "terminal": True,
        "terminal_reason": DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_TERMINAL_REASON,
        "source_model_proof": source_model,
    }
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": DRAW_FUNCTION,
                "frontiers": [],
                "terminal_frontiers": [helper_terminal, stack_terminal],
                "next_frontier": None,
                "summary": {"terminal_count": 2, "unexhausted_count": 0},
            }
        ],
        "next_frontier": None,
    }


def _allocator_after_whole_function(retained=None):
    retained = retained or _retained_frontiers_after_whole_function()
    proof = retained["functions"][0]["meta_ceiling"]["terminal_proof"]
    return {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        ),
        "post_source_context_next_dimension": proof,
        "current_ceiling": proof,
    }


def _allocator_after_stack_clean_final(retained=None):
    retained = retained or _retained_frontiers_after_stack_clean_final()
    proof = retained["functions"][0]["terminal_frontiers"][1]["source_model_proof"]
    return {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "current_ceiling": proof,
        "post_source_context_next_dimension": proof,
    }


def _discover(row=None):
    source_model = _source_model(row)
    retained = _retained_frontiers_terminal(source_model)
    return PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
        retained_frontiers=retained,
        allocator_ceiling={
            "function": DRAW_FUNCTION,
            "status": "practical-ceiling",
            "terminal_reason": (
                "retained-frontiers-all-known-frontiers-exhausted/"
                "current-source-shape-ceiling"
            ),
            "current_ceiling": retained["functions"][0]["terminal_frontiers"][0][
                "source_model_proof"
            ],
        },
    )


def _discover_post_whole(row=None):
    source_model = _whole_function_source_model(row)
    retained = _retained_frontiers_after_whole_function(source_model)
    return PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
        retained_frontiers=retained,
        allocator_ceiling=_allocator_after_whole_function(retained),
        continuation={
            "kind": "post-ceiling-source-family-continuation",
            "status": "terminal",
            "function": DRAW_FUNCTION,
            "next_unsupported_source_family": DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY,
            "next_unsupported_source_model": DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL,
        },
    )


def test_draw_post_source_context_terminal_emits_next_unsupported_dimension():
    payload = _discover()

    assert payload["kind"] == DISCOVERY_KIND
    assert payload["status"] == "unsupported-source-dimension"
    assert payload["current_floor"] == {"target": 1, "expression": 1}
    assert payload["next_unsupported_source_dimension"] == (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY
    )
    assert len(payload["source_spans"]) >= 3
    evidence = payload["retained_evidence"][0]
    assert evidence["target_score"]
    assert evidence["expression_score"]
    assert evidence["pcdump_path"]
    assert evidence["source_hunks"]
    assert not payload.get("ranked_retained_c_probes")


def test_draw_post_whole_function_terminal_does_not_repeat_whole_function_dimension():
    payload = _discover_post_whole()

    assert payload["kind"] == DISCOVERY_KIND
    assert payload["status"] == "unsupported-source-family"
    assert payload["trigger_family"] == DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    assert payload["trigger_dimension"] == DRAW_POST_SOURCE_CONTEXT_DIMENSION
    assert (
        payload["next_unsupported_source_family"]
        == DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert (
        payload["unsupported_source_expression_class"]
        == DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
    )
    assert (
        payload.get("next_unsupported_source_dimension")
        != DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert payload["exhausted_source_dimension"] == DRAW_POST_SOURCE_CONTEXT_DIMENSION
    assert DRAW_POST_SOURCE_CONTEXT_DIMENSION in payload["exhausted_dimensions"]
    evidence = payload["retained_evidence"][0]
    assert evidence["pcdump_path"]
    assert evidence["target_score"]
    assert evidence["expression_score"]
    assert evidence["source_hunks"]


def test_post_source_context_next_dimension_consumes_stack_clean_terminal():
    source_model = _stack_clean_final_source_model()
    retained = _retained_frontiers_after_stack_clean_final(source_model)
    payload = PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
        retained_frontiers=retained,
        allocator_ceiling=_allocator_after_stack_clean_final(retained),
        continuation={
            "function": DRAW_FUNCTION,
            "status": "terminal",
            "next_unsupported_source_dimension": (
                DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
            ),
            "next_unsupported_source_family": "post-ceiling-baseline-escape",
            "next_unsupported_source_model": DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL,
        },
    )

    assert payload["status"] == "unsupported-source-family"
    assert (
        payload["trigger_dimension"]
        == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert (
        payload["exhausted_source_dimension"]
        == DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
        in payload["exhausted_dimensions"]
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_MODEL
    )
    assert payload.get("next_unsupported_source_dimension") != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    serialized = json.dumps(payload)
    assert DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION not in serialized
    assert DRAW_UNSUPPORTED_SOURCE_EXPRESSION_MODEL not in serialized


def test_post_source_context_next_dimension_prefers_helper_boundary_over_stale_protected_reconcile():
    payload = _discover_helper_boundary_with_stale_protected()

    assert payload["status"] == "unsupported-source-family"
    assert payload["terminal_reason"] == (
        DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
    )
    assert payload["trigger_dimension"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    assert payload["exhausted_source_dimension"] == (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION in payload["exhausted_dimensions"]
    assert payload["next_unsupported_source_family"] == (
        DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == DRAW_HELPER_BOUNDARY_FINAL_MODEL
    assert payload["next_unsupported_source_family"] != (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert payload.get("next_unsupported_source_dimension") != (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert payload["retained_evidence"][0]["pcdump_path"]
    assert payload["retained_evidence"][0]["target_score"]
    assert payload["retained_evidence"][0]["expression_score"]


def test_post_source_context_next_dimension_prefers_loop_callsite_over_stack_clean():
    source_model = _loop_callsite_final_source_model()
    retained = _retained_frontiers_after_stack_clean_final(source_model)
    stale_stack_clean = _stack_clean_final_source_model()

    payload = PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
        retained_frontiers=retained,
        allocator_ceiling=_allocator_after_stack_clean_final(retained),
        continuation=stale_stack_clean,
    )

    assert payload["status"] == "unsupported-source-family"
    assert payload["terminal_reason"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_TERMINAL_REASON
    )
    assert payload["trigger_dimension"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )
    assert payload["exhausted_source_dimension"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_EXPRESSION_ANCHOR_SOURCE_OWNERSHIP_MODEL
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert {row["dimension_id"] for row in payload["retained_evidence"]} == {
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    }


def test_protected_reconcile_current_ceiling_beats_stale_loop_callsite_history():
    payload = _discover_protected_reconcile()

    assert payload["status"] == "unsupported-source-family"
    assert payload["trigger_family"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert payload["trigger_dimension"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
    )
    assert payload["terminal_reason"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_TERMINAL_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_model"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_MODEL
    )


def test_protected_reconcile_function_meta_synthesis_beats_stale_loop_history():
    _, retained, _ = _protected_reconcile_artifacts_with_stale_loop_history()
    proof = retained["functions"][0]["meta_ceiling"]["terminal_proof"]
    for key in (
        "next_unsupported_source_family",
        "next_unsupported_source_model",
        "terminal_reason",
        "terminal_blocker",
        "exhausted_source_dimension",
        "exhausted_dimensions",
    ):
        proof.pop(key, None)

    payload = PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        retained_frontiers=retained,
    )

    assert payload["status"] == "unsupported-source-family"
    assert payload["trigger_family"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert payload["trigger_dimension"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
    )
    assert payload["trigger_dimension"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )


def test_protected_reconcile_preserves_evidence_without_loop_exhaustion():
    payload = _discover_protected_reconcile()

    assert payload["trigger_dimension"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )
    assert payload["exhausted_source_dimension"] != (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
    )
    assert (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_DIMENSION
        not in payload["exhausted_dimensions"]
    )
    assert payload["exhausted_dimensions"] == [
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_DIMENSION
    ]
    evidence = payload["retained_evidence"][0]
    assert evidence["candidate_id"] == "draw-protected-reconcile-row-delta-retained"
    assert evidence["target_score"]
    assert evidence["expression_score"]
    assert evidence["source_hunks"]
    assert evidence["pcdump_path"]


def test_retained_frontiers_accepts_protected_reconcile_terminal_discovery(
    tmp_path,
):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_discover_protected_reconcile()), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["kind"] == DISCOVERY_KIND
    assert proof["next_unsupported_source_family"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert proof["candidate_scores"][0]["target_score"]
    assert proof["candidate_scores"][0]["expression_score"]


def test_allocator_ceiling_carries_protected_reconcile_terminal_discovery(
    tmp_path,
):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_discover_protected_reconcile()), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    assert result["status"] == "practical-ceiling"
    assert result["current_ceiling"]["next_unsupported_source_family"] == (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert result["post_source_context_next_dimension"][
        "next_unsupported_source_family"
    ] == DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY


def test_draw_post_source_context_floor_improvement_becomes_source_actionable():
    row = _score_row(target_matched=2, target_score={"matched": 2, "targeted": 3})
    payload = _discover(row)

    assert payload["status"] == "source-actionable"
    assert payload["ranked_retained_c_probes"]
    probe = payload["ranked_retained_c_probes"][0]
    assert probe["source_retained"]
    assert probe["source_hunks"]
    assert probe["pcdump_path"]
    assert probe["target_score"]
    assert probe["expression_score"]
    assert payload["next_frontier"]["actionable"] is True


def test_draw_post_whole_function_floor_improvement_still_becomes_source_actionable():
    row = _whole_function_score_row(
        target_matched=2,
        target_score={"matched": 2, "targeted": 3},
    )
    payload = _discover_post_whole(row)

    assert payload["status"] == "source-actionable"
    probe = payload["ranked_retained_c_probes"][0]
    assert probe["candidate_id"] == row["candidate_id"]
    assert probe["pcdump_path"] == row["pcdump_path"]
    assert probe["target_score"]["matched"] == 2
    assert probe["expression_score"]
    assert probe["source_hunks"]


def test_draw_post_source_context_renumbered_expression_hit_does_not_exceed_floor():
    row = _score_row(
        expression_matched=2,
        expression_score={
            "register_class": "fpr",
            "matched": 2,
            "targeted": 3,
            "renumbered": 1,
            "false_positive_virtual_id_hit_count": 0,
            "virtuals": {
                "37": {"expected": 26, "actual": 26, "matched": True},
                "46": {
                    "expected": 26,
                    "actual": 26,
                    "matched": True,
                    "renumbered": True,
                },
            },
        },
    )

    payload = _discover(row)

    assert payload["status"] == "unsupported-source-dimension"
    evidence = payload["retained_evidence"][0]
    assert evidence["expression_matched"] == 2
    assert evidence["real_expression_matched"] == 1
    assert evidence["expression_renumbering_only"] is True
    assert evidence["expression_score"]["renumbered"] == 1


def test_draw_post_source_context_target_progress_survives_renumbered_expression_hit():
    row = _score_row(
        target_matched=2,
        target_score={"matched": 2, "targeted": 3},
        expression_matched=2,
        expression_score={
            "register_class": "fpr",
            "matched": 2,
            "targeted": 3,
            "renumbered": 1,
            "virtuals": {
                "37": {"expected": 26, "actual": 26, "matched": True},
                "46": {
                    "expected": 26,
                    "actual": 26,
                    "matched": True,
                    "renumbered": True,
                },
            },
        },
    )

    payload = _discover(row)

    assert payload["status"] == "source-actionable"
    probe = payload["ranked_retained_c_probes"][0]
    assert probe["target_floor_progress"] is True
    assert probe["expression_floor_progress_real"] is False
    assert probe["expression_renumbering_only"] is True


def test_draw_post_source_context_uses_artifact_floor_when_ranking():
    source_model = _source_model(_score_row(target_matched=2))
    source_model["current_floor"] = {"target": 2, "expression": 1}

    payload = PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model=source_model,
    )

    assert payload["status"] == "unsupported-source-dimension"
    assert payload["current_floor"] == {"target": 2, "expression": 1}
    assert payload["retained_evidence"][0]["target_floor_progress"] is False


def test_post_source_context_next_dimension_cli_writes_unsupported_dimension(tmp_path):
    source_model = tmp_path / "source-model.json"
    retained = tmp_path / "retained.json"
    out = tmp_path / "next-dimension.json"
    source_model.write_text(json.dumps(_source_model()), encoding="utf-8")
    retained.write_text(json.dumps(_retained_frontiers_terminal()), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "post-source-context-next-dimension",
            "--function",
            DRAW_FUNCTION,
            "--source-model-json",
            str(source_model),
            "--retained-frontiers-json",
            str(retained),
            "--json",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == DISCOVERY_KIND
    assert payload["status"] == "unsupported-source-dimension"
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["retained_evidence"][0]["target_score"]
    assert written["retained_evidence"][0]["expression_score"]


def test_post_source_context_next_dimension_cli_writes_post_whole_terminal_family(
    tmp_path,
):
    source_model = tmp_path / "source-model.json"
    retained = tmp_path / "retained.json"
    allocator = tmp_path / "allocator.json"
    out = tmp_path / "next-family.json"
    source_model_payload = _whole_function_source_model()
    retained_payload = _retained_frontiers_after_whole_function(source_model_payload)
    source_model.write_text(json.dumps(source_model_payload), encoding="utf-8")
    retained.write_text(json.dumps(retained_payload), encoding="utf-8")
    allocator.write_text(
        json.dumps(_allocator_after_whole_function(retained_payload)),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "post-source-context-next-dimension",
            "--function",
            DRAW_FUNCTION,
            "--source-model-json",
            str(source_model),
            "--retained-frontiers-json",
            str(retained),
            "--allocator-ceiling-json",
            str(allocator),
            "--json",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "unsupported-source-family"
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == "unsupported-source-family"
    assert (
        written.get("next_unsupported_source_dimension")
        != DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )


def test_post_source_context_next_dimension_cli_writes_stack_clean_final_family(
    tmp_path,
):
    source_model = tmp_path / "source-model.json"
    retained = tmp_path / "retained.json"
    allocator = tmp_path / "allocator.json"
    out = tmp_path / "next-family.json"
    source_model_payload = _stack_clean_final_source_model()
    retained_payload = _retained_frontiers_after_stack_clean_final(
        source_model_payload
    )
    source_model.write_text(json.dumps(source_model_payload), encoding="utf-8")
    retained.write_text(json.dumps(retained_payload), encoding="utf-8")
    allocator.write_text(
        json.dumps(_allocator_after_stack_clean_final(retained_payload)),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "post-source-context-next-dimension",
            "--function",
            DRAW_FUNCTION,
            "--source-model-json",
            str(source_model),
            "--retained-frontiers-json",
            str(retained),
            "--allocator-ceiling-json",
            str(allocator),
            "--json",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "unsupported-source-family"
    assert payload["next_unsupported_source_family"] == (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_FINAL_FAMILY
    )
    assert payload.get("next_unsupported_source_dimension") != (
        DRAW_STACK_CLEAN_NO_ANCHOR_RECOVERY_DIMENSION
    )
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == payload


def test_post_source_context_next_dimension_cli_writes_helper_boundary_final_family(
    tmp_path,
):
    source_model = tmp_path / "source-model.json"
    retained = tmp_path / "retained.json"
    allocator = tmp_path / "allocator.json"
    out = tmp_path / "next-family.json"
    source_model_payload, retained_payload, allocator_payload = (
        _helper_boundary_artifacts_with_stale_protected_reconcile()
    )
    source_model.write_text(json.dumps(source_model_payload), encoding="utf-8")
    retained.write_text(json.dumps(retained_payload), encoding="utf-8")
    allocator.write_text(json.dumps(allocator_payload), encoding="utf-8")

    result = CliRunner().invoke(
        search_app,
        [
            "post-source-context-next-dimension",
            "--function",
            DRAW_FUNCTION,
            "--source-model-json",
            str(source_model),
            "--retained-frontiers-json",
            str(retained),
            "--allocator-ceiling-json",
            str(allocator),
            "--json",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "unsupported-source-family"
    assert payload["trigger_dimension"] == DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    assert payload["terminal_reason"] == (
        DRAW_HELPER_BOUNDARY_NO_EXPRESSION_PROGRESS_REASON
    )
    assert payload["next_unsupported_source_family"] == (
        DRAW_HELPER_BOUNDARY_FINAL_FAMILY
    )
    assert payload["next_unsupported_source_family"] != (
        DRAW_PROTECTED_EXPRESSION_SUBHUNK_RECONCILE_FINAL_FAMILY
    )
    assert payload.get("next_unsupported_source_dimension") != (
        DRAW_HELPER_BOUNDARY_HANDOFF_DIMENSION
    )
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == payload


def test_post_source_context_next_dimension_cli_actionable_exit_zero(tmp_path):
    source_model = tmp_path / "source-model.json"
    source_model.write_text(
        json.dumps(_source_model(_score_row(target_matched=2))),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "post-source-context-next-dimension",
            "--function",
            DRAW_FUNCTION,
            "--source-model-json",
            str(source_model),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "source-actionable"


def test_retained_frontiers_prefers_post_source_context_discovery_over_old_terminal_family(
    tmp_path,
):
    old = tmp_path / "old.json"
    discovery = tmp_path / "discovery.json"
    old.write_text(json.dumps(_source_model()), encoding="utf-8")
    discovery.write_text(json.dumps(_discover()), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[old, discovery],
    )

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["next_unsupported_source_dimension"] == (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_SOURCE_CONTEXT_UNSUPPORTED_FAMILY
    )


def test_retained_frontiers_uses_actionable_post_source_context_probe_as_next_frontier(
    tmp_path,
):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(
        json.dumps(_discover(_score_row(target_matched=2))),
        encoding="utf-8",
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )

    assert triaged["status"] == "actionable"
    frontier = triaged["functions"][0]["next_frontier"]
    assert frontier["kind"] == DISCOVERY_KIND
    assert frontier["continuation"]["source_hunks"]
    assert frontier["continuation"]["target_score"]
    assert frontier["continuation"]["expression_score"]


def test_retained_frontiers_accepts_post_whole_terminal_family_discovery(tmp_path):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_discover_post_whole()), encoding="utf-8")

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )

    proof = triaged["functions"][0]["meta_ceiling"]["terminal_proof"]
    assert proof["kind"] == DISCOVERY_KIND
    assert (
        proof["unsupported_source_expression_class"]
        == DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
    )
    assert proof["next_unsupported_source_family"] == DRAW_POST_SOURCE_CONTEXT_FINAL_FAMILY
    assert proof["next_unsupported_source_model"] == DRAW_POST_SOURCE_CONTEXT_FINAL_MODEL
    assert proof.get("next_unsupported_source_dimension") != (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert proof["candidate_scores"][0]["pcdump_path"]
    assert proof["candidate_scores"][0]["target_score"]
    assert proof["candidate_scores"][0]["expression_score"]


def test_allocator_ceiling_uses_actionable_post_source_context_discovery(tmp_path):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(
        json.dumps(_discover(_score_row(target_matched=2))),
        encoding="utf-8",
    )
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )

    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)

    assert result["status"] == "actionable"
    assert result["terminal_reason"] == (
        "post-source-context-next-dimension-source-actionable-lane"
    )
    assert any("Representative pcdump" in step for step in result["next_steps"])
    assert any("Target score" in step for step in result["next_steps"])
    assert any("Expression score" in step for step in result["next_steps"])


def test_allocator_ceiling_renders_unsupported_post_source_context_dimension(tmp_path):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_discover()), encoding="utf-8")
    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )

    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)
    text = render_allocator_ceiling_text(result)

    assert result["status"] == "practical-ceiling"
    assert result["post_source_context_next_dimension"][
        "next_unsupported_source_dimension"
    ] == DRAW_POST_SOURCE_CONTEXT_DIMENSION
    assert any(
        DRAW_POST_SOURCE_CONTEXT_DIMENSION in step
        for step in result["next_steps"]
    )
    assert "post source context next dimension: present" in text
    assert DRAW_POST_SOURCE_CONTEXT_DIMENSION in text


def test_allocator_ceiling_accepts_post_whole_terminal_family_discovery(tmp_path):
    discovery_payload = _discover_post_whole()
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(discovery_payload), encoding="utf-8")

    direct = classify_allocator_ceiling([discovery_payload], function=DRAW_FUNCTION)
    assert direct["status"] == "practical-ceiling"
    direct_proof = direct["post_source_context_next_dimension"]
    assert (
        direct_proof["unsupported_source_expression_class"]
        == DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
    )
    assert direct_proof.get("next_unsupported_source_dimension") != (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )

    triaged = triage_retained_frontiers(
        repo_root=tmp_path,
        functions=[DRAW_FUNCTION],
        artifacts=[discovery],
    )
    result = classify_allocator_ceiling([triaged], function=DRAW_FUNCTION)
    text = render_allocator_ceiling_text(result)

    assert result["status"] == "practical-ceiling"
    proof = result["post_source_context_next_dimension"]
    assert (
        proof["unsupported_source_expression_class"]
        == DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS
    )
    assert proof.get("next_unsupported_source_dimension") != (
        DRAW_POST_SOURCE_CONTEXT_DIMENSION
    )
    assert any(
        DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS in step
        for step in result["next_steps"]
    )
    assert any("Representative pcdump" in step for step in result["next_steps"])
    assert any("Target score" in step for step in result["next_steps"])
    assert any("Expression score" in step for step in result["next_steps"])
    assert "unsupported source expression class" in text
    assert DRAW_UNSUPPORTED_SOURCE_EXPRESSION_CLASS in text


def test_post_source_context_discovery_not_applicable_before_source_context_terminal():
    payload = PostSourceContextFprCeilingNextDimensionDiscovery().discover(
        function=DRAW_FUNCTION,
        source_model={
            "function": DRAW_FUNCTION,
            "status": "terminal",
            "next_unsupported_source_family": (
                "draw-no-modeled-source-actionable-family-after-"
                "alternate-fpr-expression-structure"
            ),
        },
    )

    assert payload["status"] == "not-applicable"
    assert payload["reason"] == "source-context-final-family-not-found"


def test_post_source_context_capability_and_help_are_registered():
    help_result = CliRunner().invoke(
        search_app,
        ["post-source-context-next-dimension", "--help"],
    )
    assert help_result.exit_code == 0, help_result.output
    assert "--source-model-json" in help_result.output

    capability_result = CliRunner().invoke(
        cli_app,
        [
            "capabilities",
            "search",
            "post-source-context next-dimension discovery",
        ],
    )
    assert capability_result.exit_code == 0, capability_result.output
    assert "debug search post-source-context-next-dimension" in (
        capability_result.output
    )


def test_allocator_ceiling_cli_accepts_direct_discovery_artifact(tmp_path):
    discovery = tmp_path / "discovery.json"
    discovery.write_text(json.dumps(_discover()), encoding="utf-8")

    result = CliRunner().invoke(
        cli_debug.solve_app,
        [
            "allocator-ceiling",
            "--function",
            DRAW_FUNCTION,
            "--evidence",
            str(discovery),
            "--json",
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["post_source_context_next_dimension"][
        "next_unsupported_source_dimension"
    ] == DRAW_POST_SOURCE_CONTEXT_DIMENSION
