import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app as cli_app
from src.mwcc_debug.post_source_ceiling_axis import (
    DISCOVERY_KIND,
    FAMILY_ID,
    TERMINAL_REASON,
    PostSourceCeilingAxisDiscovery,
)
from src.search.cli import search_app


DRAW_FUNCTION = "mnDiagram_DrawCellNumber"
SORT_FUNCTION = "mnDiagram_SortNamesByKOs"
DRAW_HELPER_BOUNDARY_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-helper-boundary-"
    "expression-lifetime"
)
DRAW_HELPER_BOUNDARY_TERMINAL_REASON = (
    "draw-coupled-fpr-expression-lifetime-helper-boundary-exhausted/"
    "no-expression-progress"
)
SORT_FINAL_FAMILY = (
    "sort-no-modeled-source-actionable-family-after-cross-tu-linkage"
)


def _draw_score_row() -> dict:
    return {
        "candidate_id": "block-macro-0001",
        "dimension_id": "inline-local-write-helper-block-macro",
        "source_retained": "build/diagnostics/draw/helper-boundary.c",
        "pcdump_path": "build/diagnostics/draw/helper-boundary.pcdump.txt",
        "target_score": {
            "register_class": "fpr",
            "matched": 1,
            "targeted": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": 28, "matched": True},
                "37": {"expected": 26, "actual": 27, "matched": False},
                "46": {"expected": 26, "actual": 2, "matched": False},
            },
        },
        "expression_score": {
            "register_class": "fpr",
            "matched": 0,
            "targeted": 3,
            "virtuals": {
                "32": {"expected": 28, "actual": None, "matched": False},
                "37": {"expected": 26, "actual": None, "matched": False},
                "46": {"expected": 26, "actual": None, "matched": False},
            },
        },
        "source_hunks": [{"hunk_id": "helper-boundary-h001", "old_start": 2562}],
        "structural_guard": {"accepted": True, "normalized_diff_lines": 0},
    }


def _draw_post_source_context() -> dict:
    row = _draw_score_row()
    return {
        "kind": "post-source-context-fpr-next-dimension-discovery",
        "status": "unsupported-source-family",
        "function": DRAW_FUNCTION,
        "current_floor": {"target": 1, "expression": 1},
        "trigger_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
        "trigger_dimension": "draw-coupled-fpr-expression-lifetime-helper-boundary-handoff",
        "terminal_reason": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "terminal_blocker": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
        "retained_evidence": [row],
    }


def _draw_allocator() -> dict:
    return {
        "function": DRAW_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": "expression-scored-fpr-allocator-ceiling",
        "retained_frontiers_meta_ceiling": {
            "terminal_proof": {
                "next_unsupported_source_family": DRAW_HELPER_BOUNDARY_FINAL_FAMILY,
                "terminal_reason": DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
                "candidate_scores": [_draw_score_row()],
            }
        },
    }


def _draw_first_divergence_constant_load() -> dict:
    return {
        "kind": "first-divergence-source-attribution",
        "fact": {
            "class_id": 1,
            "ig_idx": 46,
            "case": "C",
            "baseline_reg": 2,
            "baseline_reg_name": "f2",
            "target_reg": 26,
            "target_reg_name": "f26",
        },
        "source": {
            "ig_idx": 46,
            "source_kind": "fpr-temp",
            "source_expression": "lfd f46,@192(r0)",
            "source_file": "src/melee/mn/mndiagram.c",
            "source_line": None,
            "source_col": None,
            "source_confidence": "pcode-first-def",
            "candidate_spans": [],
        },
    }


def _draw_simplify_terminal() -> dict:
    return {
        "function": DRAW_FUNCTION,
        "status": "terminal",
        "terminal_blocker": "no-retained-candidate-improved-residual-force-phys",
        "candidate_count": 20,
        "progress_count": 0,
    }


def _sort_row() -> dict:
    return {
        "candidate_id": "sort-cross-tu-linkage-natural",
        "dimension_id": "sort-cross-tu-selection-swap-source-hypothesis",
        "source_retained": "build/diagnostics/sort/cross-tu.c",
        "pcdump_path": "build/diagnostics/sort/cross-tu.pcdump.txt",
        "target_score": {
            "register_class": "gpr",
            "matched": 1,
            "targeted": 2,
            "virtuals": {
                "34": {"expected": 27, "actual": 24, "matched": False},
                "44": {"expected": 25, "actual": 28, "matched": False},
            },
        },
        "source_hunks": [{"hunk_id": "sort-cross-tu-h001", "old_start": 2100}],
        "structural_guard": {"accepted": True, "normalized_diff_lines": 0},
    }


def _sort_source_model() -> dict:
    return {
        "kind": "post-ceiling-gpr-source-model-synthesis-proof",
        "status": "terminal",
        "function": SORT_FUNCTION,
        "terminal_reason": "post-ceiling-gpr-source-model-synthesis-exhausted",
        "next_unsupported_source_family": SORT_FINAL_FAMILY,
        "candidate_count": 0,
        "candidate_scores": [_sort_row()],
    }


def _sort_continuation() -> dict:
    return {
        "kind": "post-meta-source-family-continuation",
        "status": "terminal",
        "function": SORT_FUNCTION,
        "family_id": "post-meta-source-family-continuation",
        "candidate_count": 12,
        "terminal_reason": (
            "post-meta-gpr-one-hit-source-family-continuation-exhausted/"
            "protected-structural-ceiling"
        ),
        "next_unsupported_source_family": SORT_FINAL_FAMILY,
        "retained_scored_probes": [_sort_row()],
    }


def _sort_retained_frontiers() -> dict:
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": SORT_FUNCTION,
                "next_frontier": None,
                "terminal_frontiers": [
                    {
                        "terminal": True,
                        "family_id": SORT_FINAL_FAMILY,
                        "terminal_reason": "transform-family-exhausted",
                    }
                ],
                "meta_ceiling": {
                    "terminal_proof": {
                        "status": "complete",
                        "reason": "no-modeled-source-actionable-frontiers-remain",
                        "next_unsupported_source_family": SORT_FINAL_FAMILY,
                        "candidate_scores": [_sort_row()],
                    }
                },
            }
        ],
    }


def _sort_allocator() -> dict:
    return {
        "function": SORT_FUNCTION,
        "status": "practical-ceiling",
        "terminal_reason": (
            "retained-frontiers-all-known-frontiers-exhausted/"
            "current-source-shape-ceiling"
        ),
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_draw_helper_boundary_terminal_emits_fpr_backend_codegen_axis() -> None:
    payload = PostSourceCeilingAxisDiscovery().discover(
        function=DRAW_FUNCTION,
        post_source_context=_draw_post_source_context(),
        allocator_ceiling=_draw_allocator(),
    )

    assert payload["kind"] == DISCOVERY_KIND
    assert payload["status"] == "terminal"
    assert payload["family_id"] == FAMILY_ID
    assert payload["register_class"] == "fpr"
    assert payload["terminal_reason"] == TERMINAL_REASON
    assert "next_unsupported_source_family" not in payload
    assert DRAW_HELPER_BOUNDARY_FINAL_FAMILY in payload["source_ceiling_proof"][
        "closed_source_families"
    ]
    assert payload["source_ceiling_proof"]["terminal_reasons"] == [
        DRAW_HELPER_BOUNDARY_TERMINAL_REASON,
        "expression-scored-fpr-allocator-ceiling",
    ]
    assert [axis["axis_id"] for axis in payload["ranked_axes"]][:2] == [
        "fpr-expression-anchor-allocation-coupling",
        "fpr-helper-boundary-materialization",
    ]
    assert payload["ranked_axes"][0]["axis_class"] == "backend-codegen"
    assert {
        anchor["virtual"]
        for anchor in payload["anchor_evidence"]["expression_anchors"]
    } == {"32", "37", "46"}
    assert payload["modeled_non_source_axis_count"] == 0
    commands = [
        diagnostic["command_hint"]
        for axis in payload["ranked_axes"]
        for diagnostic in axis["diagnostics"]
    ]
    assert not any(
        "score-force-phys" in command and "--source" in command
        for command in commands
    )
    setup = [
        diagnostic
        for axis in payload["ranked_axes"]
        for diagnostic in axis["diagnostics"]
        if diagnostic["tool"] == "force-phys-setup"
    ][0]
    assert "debug permute setup-simplify-order-scorer" in setup["command_hint"]
    assert "--scorer-mode force-phys" in setup["command_hint"]
    assert setup["force_phys_csv"] == "32:28,37:26,46:26"
    assert setup["class_id"] == "1"


def test_draw_constant_load_first_divergence_emits_terminal_repair_lane() -> None:
    payload = PostSourceCeilingAxisDiscovery().discover(
        function=DRAW_FUNCTION,
        post_source_context=_draw_post_source_context(),
        allocator_ceiling=_draw_allocator(),
        first_divergence=_draw_first_divergence_constant_load(),
        simplify_order=_draw_simplify_terminal(),
    )

    lane = payload["source_repair_lanes"][0]
    assert lane["kind"] == "post-source-ceiling-fpr-constant-load-source-repair"
    assert lane["status"] == "terminal-blocker"
    assert lane["terminal_blocker"] == "pcode-only-fpr-constant-load-owner-unmapped"
    assert lane["constant_load_owner"] == {
        "opcode": "lfd",
        "target_register": "f46",
        "address_expression": "@192(r0)",
        "owner_status": "unmapped-pcode-constant-load",
    }
    assert {
        anchor["virtual"]
        for anchor in lane["expression_anchors"]
    } == {"32", "37", "46"}
    assert lane["bounded_probe_result"]["terminal_blocker"] == (
        "no-retained-candidate-improved-residual-force-phys"
    )


def test_sort_terminal_emits_gpr_backend_codegen_axis() -> None:
    payload = PostSourceCeilingAxisDiscovery().discover(
        function=SORT_FUNCTION,
        source_model=_sort_source_model(),
        continuation=_sort_continuation(),
        retained_frontiers=_sort_retained_frontiers(),
        allocator_ceiling=_sort_allocator(),
    )

    assert payload["status"] == "terminal"
    assert payload["family_id"] == FAMILY_ID
    assert payload["register_class"] == "gpr"
    assert SORT_FINAL_FAMILY in payload["source_ceiling_proof"][
        "closed_source_families"
    ]
    assert [axis["axis_id"] for axis in payload["ranked_axes"]][:2] == [
        "gpr-case-c-live-range-allocation",
        "gpr-selection-swap-pointer-materialization",
    ]
    assert {
        anchor["virtual"]
        for anchor in payload["anchor_evidence"]["target_anchors"]
    } == {"34", "44"}
    assert all(
        axis["axis_class"] == "backend-codegen"
        for axis in payload["ranked_axes"]
    )


def test_post_source_ceiling_axis_cli_writes_terminal_json(tmp_path: Path) -> None:
    post_source = _write_json(tmp_path / "draw-post-source.json", _draw_post_source_context())
    allocator = _write_json(tmp_path / "draw-allocator.json", _draw_allocator())
    out = tmp_path / "axis.json"

    result = CliRunner().invoke(
        search_app,
        [
            "post-source-ceiling-axis",
            "--function",
            DRAW_FUNCTION,
            "--post-source-context-json",
            str(post_source),
            "--allocator-ceiling-json",
            str(allocator),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "terminal"
    assert written["family_id"] == FAMILY_ID
    assert "debug inspect first-divergence" in payload["ranked_axes"][0]["diagnostics"][0][
        "command_hint"
    ]
    assert all(
        "--source" not in diagnostic["command_hint"]
        for axis in payload["ranked_axes"]
        for diagnostic in axis["diagnostics"]
        if "score-force-phys" in diagnostic["command_hint"]
    )


def test_aggregate_inputs_are_scoped_to_requested_function() -> None:
    retained = _sort_retained_frontiers()
    retained["functions"].insert(
        0,
        {
            "function": "OtherFunction",
            "next_frontier": None,
            "terminal_frontiers": [
                {
                    "terminal": True,
                    "family_id": "other-source-family",
                    "terminal_reason": "transform-family-exhausted",
                }
            ],
            "meta_ceiling": {
                "terminal_proof": {
                    "status": "complete",
                    "next_unsupported_source_family": "other-source-family",
                    "candidate_scores": [
                        {
                            "candidate_id": "other-candidate",
                            "target_score": {
                                "register_class": "gpr",
                                "virtuals": {
                                    "999": {"expected": 1, "actual": 2},
                                },
                            },
                        }
                    ],
                }
            },
        },
    )

    payload = PostSourceCeilingAxisDiscovery().discover(
        function=SORT_FUNCTION,
        retained_frontiers=retained,
        allocator_ceiling=_sort_allocator(),
    )

    assert "other-source-family" not in payload["source_ceiling_proof"][
        "closed_source_families"
    ]
    assert {
        anchor["virtual"]
        for anchor in payload["anchor_evidence"]["target_anchors"]
    } == {"34", "44"}

    other_payload = PostSourceCeilingAxisDiscovery().discover(
        function="MissingFunction",
        retained_frontiers=retained,
    )
    assert other_payload["status"] == "not-applicable"
    assert other_payload["reason"] == "source-ceiling-not-terminal"


def test_anchor_evidence_preserves_distinct_candidate_rows() -> None:
    source_model = _sort_source_model()
    source_model["candidate_scores"].append(
        {
            **_sort_row(),
            "candidate_id": "sort-cross-tu-alternate",
            "pcdump_path": "build/diagnostics/sort/alternate.pcdump.txt",
            "target_score": {
                "register_class": "gpr",
                "matched": 0,
                "targeted": 2,
                "virtuals": {
                    "34": {"expected": 27, "actual": 31, "matched": False},
                },
            },
        }
    )

    payload = PostSourceCeilingAxisDiscovery().discover(
        function=SORT_FUNCTION,
        source_model=source_model,
    )

    anchors = [
        anchor
        for anchor in payload["anchor_evidence"]["target_anchors"]
        if anchor["virtual"] == "34"
    ]
    assert {anchor["actual"] for anchor in anchors} == {24, 31}
    assert {anchor["candidate_id"] for anchor in anchors} == {
        "sort-cross-tu-linkage-natural",
        "sort-cross-tu-alternate",
    }
    assert all(
        "target_score" in row
        for row in payload["anchor_evidence"]["retained_score_rows"]
    )


def test_post_source_ceiling_axis_capability_and_help_are_registered() -> None:
    help_result = CliRunner().invoke(
        search_app,
        ["post-source-ceiling-axis", "--help"],
    )
    assert help_result.exit_code == 0, help_result.output
    assert "--post-source-context" in help_result.output

    capability_result = CliRunner().invoke(
        cli_app,
        [
            "capabilities",
            "search",
            "post-source-ceiling backend codegen axis",
        ],
    )
    assert capability_result.exit_code == 0, capability_result.output
    assert "debug search post-source-ceiling-axis" in capability_result.output
