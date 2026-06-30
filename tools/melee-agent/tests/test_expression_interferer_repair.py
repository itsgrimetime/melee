import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.expression_interferer_repair import (
    ExpressionRepairCandidate,
    ProtectedExpressionPolicy,
    _attempted_route_set,
    _attempted_routes_for_post_bridge,
    attach_residual_labels,
    build_terminal_summary,
    derive_focus_force_map,
    evaluate_candidate,
    expression_problem_source_reachable,
    generate_source_repair_candidates,
    rank_candidates,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mwcc_debug" / "issue876"
runner = CliRunner()
_LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES = (
    "retained_fpr_case_c_target_live_range_repair",
    "protected_expression_row_product_generation",
    "product_operand_ownership",
    "row_offset_first_scaled_ownership",
    "product_sink_ownership",
    "row_offset_sink_branch_ownership",
    "digit_guarded_statement_motion",
)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _anchor(
    baseline_virtual: int,
    name: str,
    *,
    expected: int,
    actual: int | None,
    candidate_virtual: int | None = None,
    matched: bool | None = None,
    status: str = "ok",
    virtual_id_matched: bool = False,
    virtual_id_false_positive: bool = False,
    expression: str | None = None,
    source_file: str | None = None,
    source_line: int | None = None,
    first_def_opcode: str | None = None,
    first_def_operands: str | None = None,
) -> dict:
    if matched is None:
        matched = actual == expected
    source = {
        "kind": "local",
        "confidence": "fpr-expression-order",
        "name": name,
    }
    if expression is not None:
        source["expression"] = expression
    if source_file is not None:
        source["source_file"] = source_file
    if source_line is not None:
        source["source_line"] = source_line
    if first_def_operands is not None or first_def_opcode is not None:
        source["first_def"] = {
            "opcode": first_def_opcode or "fmuls",
            "operands": first_def_operands or "",
        }
    signature = {
        "kind": "source-expression" if expression is not None else "name",
        "source_kind": "local",
        "name": name,
    }
    if expression is not None:
        signature["expression"] = expression
    return {
        "baseline_virtual": baseline_virtual,
        "expected": expected,
        "signature": signature,
        "baseline_source": dict(source),
        "candidate_source": dict(source),
        "candidate_virtual": (
            baseline_virtual if candidate_virtual is None else candidate_virtual
        ),
        "actual": actual,
        "matched": matched,
        "status": status,
        "virtual_id_matched": virtual_id_matched,
        "virtual_id_false_positive": virtual_id_false_positive,
    }


def _expression_score(*anchors: dict) -> dict:
    false_positive_hits = [
        anchor
        for anchor in anchors
        if anchor.get("virtual_id_false_positive")
    ]
    matched = sum(1 for anchor in anchors if anchor.get("matched"))
    return {
        "register_class": "fpr",
        "matched": matched,
        "targeted": len(anchors),
        "virtual_distance": len(anchors) - matched,
        "false_positive_virtual_id_hit_count": len(false_positive_hits),
        "false_positive_virtual_id_hits": false_positive_hits,
        "virtuals": {
            str(anchor["baseline_virtual"]): anchor
            for anchor in anchors
        },
    }


def _policy() -> ProtectedExpressionPolicy:
    return ProtectedExpressionPolicy(focus_name="col_offset_product_fpr")


def _retained_draw_cell_source(function: str = "mnDiagram_DrawCellNumber") -> str:
    return (
        "typedef float f32;\n"
        "typedef unsigned char u8;\n"
        "typedef int s32;\n"
        "typedef struct Diagram { void** jobjs; } Diagram;\n"
        "extern f32 HSD_JObjGetTranslationY(void* jobj);\n"
        "extern int mn_GetDigitCount(int value);\n"
        f"void {function}(void* gobj, u8 arg1, u8 arg2, int value)\n"
        "{\n"
        "    f32 row_offset;\n"
        "    Diagram* data_alias;\n"
        "    f32 row_offset_adj;\n"
        "    void* jobj;\n"
        "    void* jobj2;\n"
        "    Diagram* data;\n"
        "    s32 digit_count;\n"
        "    f32 y_spacing;\n"
        "    f32 base;\n"
        "    f32 rowf;\n"
        "    f32 col_offset;\n"
        "    f32 col_cast_owner_fpr;\n"
        "    f32 col_offset_product_fpr;\n"
        "    u8 col = arg1;\n"
        "    u8 row = arg2;\n"
        "\n"
        "    data = gobj;\n"
        "    data_alias = data;\n"
        "    jobj = data->jobjs[9];\n"
        "    base = HSD_JObjGetTranslationY(jobj);\n"
        "    jobj2 = data->jobjs[10];\n"
        "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;\n"
        "\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    col_offset_product_fpr = y_spacing * col_cast_owner_fpr;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    sink(data_alias, digit_count, col, row, col_offset, row_offset_adj);\n"
        "}\n"
    )


def _row_offset_only_source(function: str = "mnDiagram_DrawCellNumber") -> str:
    return (
        "typedef float f32;\n"
        "extern f32 HSD_JObjGetTranslationY(void* jobj);\n"
        f"void {function}(void* jobj2, f32 base, f32 rowf)\n"
        "{\n"
        "    f32 row_offset;\n"
        "\n"
        "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;\n"
        "    row_offset *= rowf;\n"
        "    sink(row_offset);\n"
        "}\n"
    )


def _row_product_sink_source(function: str = "mnDiagram_DrawCellNumber") -> str:
    return (
        "typedef float f32;\n"
        "typedef unsigned char u8;\n"
        "typedef int s32;\n"
        "typedef struct Diagram { void** jobjs; } Diagram;\n"
        "extern f32 HSD_JObjGetTranslationY(void* jobj);\n"
        "extern void HSD_JObjSetTranslateX(void* jobj, f32 value);\n"
        "extern void HSD_JObjSetTranslateY(void* jobj, f32 value);\n"
        "extern int mn_GetDigitCount(int value);\n"
        f"void {function}(void* gobj, u8 arg1, u8 arg2, int value)\n"
        "{\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    void* jobj;\n"
        "    void* jobj2;\n"
        "    Diagram* data;\n"
        "    s32 digit_count;\n"
        "    f32 y_spacing;\n"
        "    f32 base;\n"
        "    f32 rowf;\n"
        "    f32 col_offset;\n"
        "    f32 col_cast_owner_fpr;\n"
        "    f32 col_offset_product_fpr;\n"
        "    u8 col = arg1;\n"
        "    u8 row = arg2;\n"
        "\n"
        "    data = gobj;\n"
        "    jobj = data->jobjs[9];\n"
        "    base = HSD_JObjGetTranslationY(jobj);\n"
        "    jobj2 = data->jobjs[10];\n"
        "    row_offset = HSD_JObjGetTranslationY(jobj2) - base;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    col_offset_product_fpr = y_spacing * col_cast_owner_fpr;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    if (row < 10) HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "    else HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "    if (col < 10) HSD_JObjSetTranslateX(jobj, base + col_offset);\n"
        "    else HSD_JObjSetTranslateX(jobj, base + col_offset + 1.0f);\n"
        "    sink(digit_count, col, row);\n"
        "}\n"
    )


def _multi_line_product_sink_source(function: str = "mnDiagram_DrawCellNumber") -> str:
    return _row_product_sink_source(function).replace(
        "    if (col < 10) HSD_JObjSetTranslateX(jobj, base + col_offset);\n"
        "    else HSD_JObjSetTranslateX(jobj, base + col_offset + 1.0f);\n",
        "    if (col < 10) {\n"
        "        HSD_JObjSetTranslateX(\n"
        "            jobj, base + col_offset);\n"
        "    } else {\n"
        "        HSD_JObjSetTranslateX(\n"
        "            jobj, base + col_offset + 1.0f);\n"
        "    }\n",
    )


def _live_y_offset_scaled_source(function: str = "mnDiagram_DrawCellNumber") -> str:
    return (
        "typedef float f32;\n"
        "typedef unsigned char u8;\n"
        "typedef int s32;\n"
        "typedef struct Diagram { void** jobjs; } Diagram;\n"
        "extern f32 HSD_JObjGetTranslationY(void* jobj);\n"
        "extern int mn_GetDigitCount(int value);\n"
        f"void {function}(void* gobj, u8 arg1, u8 arg2, int value)\n"
        "{\n"
        "    f32 y_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    void* jobj;\n"
        "    void* jobj2;\n"
        "    Diagram* data;\n"
        "    s32 digit_count;\n"
        "    f32 y_spacing;\n"
        "    f32 base;\n"
        "    f32 rowf;\n"
        "    f32 col_offset;\n"
        "    u8 col = arg1;\n"
        "    u8 row = arg2;\n"
        "\n"
        "    data = gobj;\n"
        "    jobj = data->jobjs[9];\n"
        "    base = HSD_JObjGetTranslationY(jobj);\n"
        "    jobj2 = data->jobjs[10];\n"
        "    y_offset = HSD_JObjGetTranslationY(jobj2) - base;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    sink(digit_count, col_offset, row_offset_adj);\n"
        "}\n"
    )


def _generation_by_id(source: str, *, max_candidates: int = -1) -> dict[str, dict]:
    generation = generate_source_repair_candidates(
        source,
        function="mnDiagram_DrawCellNumber",
        include_source=True,
        max_candidates=max_candidates,
    )
    assert generation["status"] == "generated"
    return {
        candidate["candidate_id"]: candidate
        for candidate in generation["candidates"]
    }


def test_protected_expression_policy_rejects_raw_virtual_false_hit() -> None:
    score = _expression_score(
        _anchor(
            32,
            "col_offset_product_fpr",
            expected=28,
            actual=28,
            virtual_id_matched=True,
        ),
        _anchor(
            33,
            "digit_pair_f33_f34",
            expected=26,
            actual=30,
            matched=False,
            virtual_id_matched=True,
            virtual_id_false_positive=True,
        ),
        _anchor(39, "digit_pair_f39_f40_f41", expected=29, actual=29),
    )
    candidate = ExpressionRepairCandidate(
        candidate_id="raw-virtual-progress",
        target_score={"matched": 6, "virtual_distance": 0},
        expression_score=score,
        structural_guard={"accepted": True},
        residual=None,
    )

    assessment = evaluate_candidate(candidate, _policy())

    assert assessment.accepted is False
    assert "protected-expression-regressed" in assessment.blockers
    assert "protected-virtual-id-false-positive" in assessment.blockers
    assert assessment.recommendation == "reject"


def test_focus_force_map_uses_candidate_virtual_after_renumber() -> None:
    score = _expression_score(
        _anchor(
            32,
            "col_offset_product_fpr",
            expected=28,
            actual=25,
            candidate_virtual=33,
            matched=False,
        ),
        _anchor(33, "digit_pair_f33_f34", expected=26, actual=26),
    )

    assert derive_focus_force_map(score, _policy()) == {33: 28}


def test_case_a_residual_prefers_expression_label_over_source_bridge_gpr_name() -> None:
    score = _expression_score(
        _anchor(32, "col_offset_product_fpr", expected=28, actual=25),
        _anchor(33, "digit_pair_f33_f34", expected=26, actual=26),
    )
    residual = {
        "case": "A",
        "class_id": 1,
        "ig_idx": 32,
        "baseline_reg": 25,
        "target_reg": 28,
        "blocker_ig": 38,
        "source": {
            "var_name": "gobj",
            "confidence": "best-guess",
        },
    }

    labeled = attach_residual_labels(
        residual,
        expression_score=score,
        policy=_policy(),
        blocker_attribution=None,
    )

    assert labeled["focus_label"] == "col_offset_product_fpr"
    assert labeled["advisory_focus_name"] == "gobj"
    assert labeled["advisory_focus_confidence"] == "best-guess"
    assert labeled["advisory_focus_role"] == "low-confidence-diagnostic"


def test_case_a_blocker_source_attached_from_fpr_explain_virtuals() -> None:
    score = _expression_score(
        _anchor(32, "col_offset_product_fpr", expected=28, actual=25),
        _anchor(33, "digit_pair_f33_f34", expected=26, actual=26),
    )
    residual = {
        "case": "A",
        "class_id": 1,
        "ig_idx": 32,
        "baseline_reg": 25,
        "target_reg": 28,
        "blocker_ig": 38,
    }
    blocker_attribution = {
        "virtuals": [
            {
                "virtual": 38,
                "source": {
                    "kind": "local",
                    "confidence": "fpr-expression-order",
                    "name": "row_offset",
                    "expression": "HSD_JObjGetTranslationY(jobj2) - base",
                    "first_def": {
                        "opcode": "fsubs",
                        "operands": "f38,f46,f39",
                    },
                },
            },
        ],
    }

    labeled = attach_residual_labels(
        residual,
        expression_score=score,
        policy=_policy(),
        blocker_attribution=blocker_attribution,
    )

    assert labeled["blocker_source"] == "row_offset"
    assert labeled["blocker_source_confidence"] == "fpr-expression-order"
    assert labeled["blocker_first_def"]["opcode"] == "fsubs"


def test_candidate_ranking_keeps_5of6_protected_over_2of6_select_order() -> None:
    case_a = ExpressionRepairCandidate(
        candidate_id="natural-5of6-case-a",
        expression_score=_expression_score(
            _anchor(32, "col_offset_product_fpr", expected=28, actual=25),
            _anchor(33, "digit_pair_f33_f34", expected=26, actual=26),
            _anchor(34, "digit_pair_f33_f34_extra", expected=26, actual=26),
            _anchor(39, "digit_pair_f39_f40_f41", expected=29, actual=29),
            _anchor(40, "digit_pair_f39_f40_f41_extra1", expected=29, actual=29),
            _anchor(41, "digit_pair_f39_f40_f41_extra2", expected=29, actual=29),
        ),
        target_score={"matched": 5, "virtual_distance": 1},
        structural_guard={"accepted": True},
        residual={
            "case": "A",
            "ig_idx": 32,
            "baseline_reg": 25,
            "target_reg": 28,
            "blocker_ig": 38,
            "blocker_source": "row_offset",
        },
    )
    select_order = ExpressionRepairCandidate(
        candidate_id="select-order-2of6-c2",
        expression_score=_expression_score(
            _anchor(32, "col_offset_product_fpr", expected=28, actual=30),
            _anchor(33, "digit_pair_f33_f34", expected=26, actual=24),
            _anchor(34, "digit_pair_f33_f34_extra", expected=26, actual=26),
            _anchor(39, "digit_pair_f39_f40_f41", expected=29, actual=31),
            _anchor(40, "digit_pair_f39_f40_f41_extra1", expected=29, actual=29),
            _anchor(41, "digit_pair_f39_f40_f41_extra2", expected=29, actual=27),
        ),
        target_score={"matched": 2, "virtual_distance": 4},
        structural_guard={"accepted": True},
        residual={
            "case": "C2",
            "ig_idx": 32,
            "baseline_reg": 30,
            "target_reg": 28,
        },
        exploratory=True,
    )

    ranked = rank_candidates([select_order, case_a], _policy())

    assert ranked[0].candidate.candidate_id == "natural-5of6-case-a"
    assert ranked[1].candidate.candidate_id == "select-order-2of6-c2"
    assert ranked[1].recommendation == "exploratory-only"


def test_terminal_summary_names_case_a_and_c2_blockers() -> None:
    case_a = ExpressionRepairCandidate.from_payload(
        _load_fixture("natural_5of6_case_a.json")
    )
    c2 = ExpressionRepairCandidate.from_payload(
        _load_fixture("select_order_c2_regressed.json")
    )

    summary = build_terminal_summary(
        [case_a, c2],
        _policy(),
        attempted_families=["product-plan", "select-order"],
        recombine_status="exhausted",
    )

    assert summary["status"] == "blocked"
    assert summary["kind"] == "expression-scored-fpr-case-a-c2-exhaustion"
    assert summary["focus"]["name"] == "col_offset_product_fpr"
    assert summary["focus"]["expected"] == 28
    assert "row_offset" in summary["remaining_blockers"][0]["reason"]
    assert "product" in summary["remaining_blockers"][0]["reason"]
    assert any(
        blocker["case"] == "C2"
        and "sticky-pool" in blocker["reason"]
        for blocker in summary["remaining_blockers"]
    )


def test_terminal_summary_infers_case_c2_expression_register_swap() -> None:
    candidate = ExpressionRepairCandidate(
        candidate_id="live-row-col-swap",
        expression_score=_expression_score(
            _anchor(32, "col_offset", expected=28, actual=26),
            _anchor(37, "row_offset", expected=26, actual=28),
        ),
        structural_guard={"accepted": True},
    )

    default_summary = build_terminal_summary([candidate], _policy())

    assert default_summary["status"] == "blocked"
    default_blocker = default_summary["remaining_blockers"][0]
    assert default_blocker["case"] == "C2"
    assert default_blocker["focus"] == "col_offset"
    assert default_blocker["paired_source"] == "row_offset"
    assert default_blocker["current_focus_reg"] == 26
    assert default_blocker["target_reg"] == 28
    assert "sticky-pool" in default_blocker["reason"]

    summary = build_terminal_summary(
        [candidate],
        ProtectedExpressionPolicy(focus_name="col_offset"),
    )

    assert summary["status"] == "blocked"
    blocker = summary["remaining_blockers"][0]
    assert blocker["case"] == "C2"
    assert blocker["focus"] == "col_offset"
    assert blocker["paired_source"] == "row_offset"
    assert blocker["current_focus_reg"] == 26
    assert blocker["target_reg"] == 28
    assert "sticky-pool" in blocker["reason"]

    generation = generate_source_repair_candidates(
        _live_y_offset_scaled_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=default_summary,
        include_source=False,
        max_candidates=-1,
    )

    assert generation["status"] == "generated"
    assert generation["blocker_cases"] == ["C2"]
    assert any(
        "C2" in candidate["blocker_cases"]
        for candidate in generation["candidates"]
    )


def test_terminal_summary_c2_swap_includes_sticky_pool_bridge_payload() -> None:
    candidate = ExpressionRepairCandidate(
        candidate_id="issue898-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                source_file="src/melee/mn/mndiagram.c",
                source_line=2564,
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                source_file="src/melee/mn/mndiagram.c",
                source_line=2561,
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )

    summary = build_terminal_summary(
        [candidate],
        ProtectedExpressionPolicy(focus_name="col_offset"),
    )

    blocker = summary["remaining_blockers"][0]
    bridge = blocker["sticky_pool_bridge"]
    assert blocker["case"] == "C2"
    assert bridge["status"] == "ready"
    assert bridge["focus_anchor"]["label"] == "col_offset"
    assert bridge["paired_anchor"]["label"] == "row_offset"
    assert bridge["focus_upstream_fpr_operands"] == [34, 46]
    assert bridge["product_anchor"]["label"] == "col_offset"
    assert bridge["product_upstream_fpr_operands"] == [34, 46]

    actions = bridge["source_actionable_product_operand_owner_actions"]
    assert {action["candidate_id"] for action in actions} == {
        "product-col-cast-owner-materialize",
        "product-y-spacing-owner-materialize",
        "product-combined-operand-owners",
    }
    assert {
        action["owner"]
        for action in actions
    } >= {"col_cast_owner_fpr", "y_spacing_owner_fpr"}
    assert all(
        action["source_actionability"] == "local-expression"
        for action in actions
    )


def test_terminal_summary_c2_sticky_pool_bridge_plan_is_not_pair_only() -> None:
    candidate = ExpressionRepairCandidate(
        candidate_id="issue898-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )

    summary = build_terminal_summary(
        [candidate],
        ProtectedExpressionPolicy(focus_name="col_offset"),
    )

    bridge = summary["remaining_blockers"][0]["sticky_pool_bridge"]
    assert bridge["pair_only_orders_to_avoid"] == [[32, 37], [37, 32]]
    assert {
        target["kind"]
        for target in bridge["follow_up_targets"]
    } >= {"pressure_probe", "select_order_probe", "force_probe"}
    for target in bridge["follow_up_targets"]:
        assert target["pair_only"] is False
        assert target.get("target_virtuals") not in ([37, 32], [32, 37])
    assert any(
        {34, 46} <= set(target.get("target_virtuals", ()))
        for target in bridge["follow_up_targets"]
    )


def test_terminal_summary_c2_sticky_pool_bridge_marks_support_order_verify_only(
) -> None:
    candidate = ExpressionRepairCandidate(
        candidate_id="issue899-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )

    summary = build_terminal_summary(
        [candidate],
        ProtectedExpressionPolicy(focus_name="col_offset"),
    )

    bridge = summary["remaining_blockers"][0]["sticky_pool_bridge"]
    assert bridge["support_order_policy"] == {
        "avoid_already_satisfied_as_main_route": True,
        "requires_baseline_unsatisfied_for_primary_route": True,
    }
    by_kind = {
        group["kind"]: group
        for group in bridge["select_order_target_groups"]
    }
    assert by_kind["product-support-before-product"]["target_pairs"] == [
        [34, 32],
        [46, 32],
    ]
    assert (
        by_kind["product-support-before-product"]["route_role"]
        == "verify-only-if-already-satisfied"
    )
    assert by_kind["row-col-crossing"]["target_pairs"] == [[32, 37]]
    assert by_kind["row-col-crossing"]["route_role"] == "primary-c2-pair"
    assert by_kind["product-before-support"]["target_pairs"] == [
        [32, 34],
        [32, 46],
    ]
    assert any(
        target.get("target_virtuals") == [34, 46, 32, 37]
        for target in bridge["follow_up_targets"]
    )


def test_terminal_summary_c2_sticky_pool_bridge_includes_row_fsubs_owner_repair_action(
) -> None:
    candidate = ExpressionRepairCandidate(
        candidate_id="issue899-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )

    summary = build_terminal_summary(
        [candidate],
        ProtectedExpressionPolicy(focus_name="col_offset"),
    )

    repair = summary["remaining_blockers"][0]["sticky_pool_bridge"][
        "row_fsubs_owner_repair"
    ]
    assert repair["status"] == "candidate"
    assert repair["target_ig"] == 37
    assert repair["expected_phys"] == 26
    assert repair["source_name"] == "row_offset"
    assert repair["first_def_opcode"] == "fsubs"
    assert repair["first_def_operands"] == ["f37", "f43", "f38"]
    assert repair["source_expression"] == "HSD_JObjGetTranslationY(jobj2) - base"
    assert set(repair["candidate_ids"]) == {
        "row-fsubs-call-result-owner",
        "row-fsubs-owner-temp",
    }
    assert repair["requires_expression_score_validation"] is True


def test_issue876_fixture_force_proof_marks_problem_source_reachable() -> None:
    natural = ExpressionRepairCandidate.from_payload(
        _load_fixture("natural_5of6_case_a.json")
    )
    force = ExpressionRepairCandidate.from_payload(_load_fixture("force_6of6.json"))

    proof = expression_problem_source_reachable(natural, force, _policy())

    assert proof == {
        "source_reachable": True,
        "natural_focus_actual": 25,
        "force_focus_actual": 28,
        "focus_expected": 28,
        "protected_preserved": 5,
    }


def test_issue876_fixture_select_order_not_recommended_when_protected_hits_drop(
) -> None:
    select_order = ExpressionRepairCandidate.from_payload(
        _load_fixture("select_order_c2_regressed.json")
    )

    assessment = evaluate_candidate(select_order, _policy())

    assert assessment.accepted is False
    assert assessment.recommendation == "exploratory-only"
    assert "protected-expression-regressed" in assessment.blockers


def test_issue876_fixture_terminal_summary_matches_governance_stop_condition() -> None:
    candidates = [
        ExpressionRepairCandidate.from_payload(
            _load_fixture("natural_5of6_case_a.json")
        ),
        ExpressionRepairCandidate.from_payload(
            _load_fixture("select_order_c2_regressed.json")
        ),
        ExpressionRepairCandidate.from_payload(
            _load_fixture("manual_product_before_row_0of6.json")
        ),
    ]

    summary = build_terminal_summary(
        candidates,
        _policy(),
        attempted_families=[
            "product-plan",
            "select-order",
            "manual-product-before-row",
        ],
        recombine_status="manual-subhunk-required",
    )

    assert summary["status"] == "blocked"
    assert summary["best_candidate"]["candidate_id"] == "natural-5of6-case-a"
    assert summary["protected"]["best_preserved"] == 5
    assert summary["attempted_families"] == [
        "product-plan",
        "select-order",
        "manual-product-before-row",
    ]
    assert summary["recombine_status"] == "manual-subhunk-required"
    assert summary["remaining_blockers"][0]["blocker_source"] == "row_offset"


def test_cli_emits_expression_interferer_repair_terminal_summary() -> None:
    candidate_paths = ",".join(
        str(FIXTURE_DIR / name)
        for name in (
            "natural_5of6_case_a.json",
            "select_order_c2_regressed.json",
        )
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "expression-interferer-repair",
            "--candidate-json",
            candidate_paths,
            "--attempted-families",
            "product-plan,select-order",
            "--recombine-status",
            "exhausted",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["status"] == "blocked"
    assert summary["best_candidate"]["candidate_id"] == "natural-5of6-case-a"
    assert summary["remaining_blockers"][0]["case"] == "A"
    assert summary["attempted_families"] == ["product-plan", "select-order"]


def test_source_generation_emits_row_product_candidates_with_hunks() -> None:
    candidates = [
        ExpressionRepairCandidate.from_payload(
            _load_fixture("natural_5of6_case_a.json")
        ),
        ExpressionRepairCandidate.from_payload(
            _load_fixture("select_order_c2_regressed.json")
        ),
    ]
    terminal_summary = build_terminal_summary(candidates, _policy())

    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=terminal_summary,
        include_source=True,
        max_candidates=-1,
    )

    assert generation["status"] == "generated"
    assert generation["blocker_cases"] == ["A", "C2"]
    assert {
        "protected_expression_row_product_generation",
        "row_offset_first_scaled_ownership",
        "product_sink_ownership",
    } <= set(generation["families"])
    by_id = {
        candidate["candidate_id"]: candidate
        for candidate in generation["candidates"]
    }
    assert {
        "row-offset-owner-split",
        "product-owner-sticky-copy",
        "row-owner-product-interleave",
        "row-first-def-owner-copy",
        "row-scaled-def-owner-copy",
        "product-col-offset-sink-owner",
    } <= set(by_id)
    row_candidate = by_id["row-offset-owner-split"]
    assert row_candidate["source_hunks"]
    assert "f32 row_offset_owner_fpr;" in row_candidate["source_text"]
    assert "row_offset_owner_fpr = row_offset;" in row_candidate["source_text"]
    assert "row_offset = row_offset_owner_fpr * rowf;" in row_candidate["source_text"]
    product_candidate = by_id["product-owner-sticky-copy"]
    assert "f32 col_offset_product_owner_fpr;" in product_candidate["source_text"]
    assert (
        "col_offset_product_fpr = y_spacing * col_cast_owner_fpr;"
        in product_candidate["source_text"]
    )
    assert (
        "col_offset_product_owner_fpr = col_offset_product_fpr;"
        in product_candidate["source_text"]
    )
    assert "col_offset_product_fpr = col_offset_product_owner_fpr;" not in (
        product_candidate["source_text"]
    )


def test_source_generation_blocks_when_only_attempted_family_remains() -> None:
    generation = generate_source_repair_candidates(
        _row_offset_only_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary={
            "kind": "expression-score-after-source-generation",
            "attempted_families": ["protected_expression_row_product_generation"],
        },
        include_source=True,
        max_candidates=-1,
    )

    assert generation["status"] == "blocked"
    assert generation["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    assert generation["families"] == []
    assert generation["candidates"] == []
    assert generation["suppressed_families"] == [
        "protected_expression_row_product_generation"
    ]
    assert generation["candidate_ids"] == ["row-offset-owner-split"]


def test_source_generation_filters_attempted_family_before_candidate_limit() -> None:
    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary={
            "kind": "expression-score-after-source-generation",
            "attempted_families": ["protected-expression-row-product-generation"],
        },
        include_source=False,
        max_candidates=1,
    )

    assert generation["status"] == "generated"
    assert generation["candidates"]
    assert generation["candidates"][0]["family"] != (
        "protected_expression_row_product_generation"
    )
    assert "protected_expression_row_product_generation" in (
        generation["suppressed_families"]
    )
    assert "row-offset-owner-split" in generation["suppressed_candidate_ids"]


def test_source_generation_second_gen_handles_live_y_offset_scaled_shape() -> None:
    by_id = _generation_by_id(_live_y_offset_scaled_source())

    assert "product-local-materialize" in by_id
    assert "product-col-cast-owner-materialize" in by_id
    assert "product-y-spacing-owner-materialize" in by_id
    assert "product-combined-operand-owners" in by_id
    assert "row-first-def-owner-copy" in by_id
    assert "row-scaled-adj-direct-owner" in by_id
    product_text = by_id["product-local-materialize"]["source_text"]
    assert "f32 col_offset_product_fpr;" in product_text
    assert "col_offset_product_fpr = y_spacing * (f32) col;" in product_text
    row_text = by_id["row-first-def-owner-copy"]["source_text"]
    assert "row_offset_first_owner_fpr = y_offset;" in row_text
    assert "row_offset = row_offset_first_owner_fpr * rowf;" in row_text


def test_source_generation_emits_product_operand_owner_candidates() -> None:
    by_id = _generation_by_id(_live_y_offset_scaled_source())

    col_cast = by_id["product-col-cast-owner-materialize"]
    assert col_cast["family"] == "product_operand_ownership"
    assert "f32 col_cast_owner_fpr;" in col_cast["source_text"]
    assert "col_cast_owner_fpr = (f32) col;" in col_cast["source_text"]
    assert "col_offset = y_spacing * col_cast_owner_fpr;" in (
        col_cast["source_text"]
    )

    y_spacing = by_id["product-y-spacing-owner-materialize"]
    assert y_spacing["family"] == "product_operand_ownership"
    assert "f32 y_spacing_owner_fpr;" in y_spacing["source_text"]
    assert "y_spacing_owner_fpr = y_spacing;" in y_spacing["source_text"]
    assert "col_offset = y_spacing_owner_fpr * (f32) col;" in (
        y_spacing["source_text"]
    )

    combined = by_id["product-combined-operand-owners"]
    assert combined["family"] == "product_operand_ownership"
    assert "f32 y_spacing_owner_fpr;" in combined["source_text"]
    assert "f32 col_cast_owner_fpr;" in combined["source_text"]
    assert "y_spacing_owner_fpr = y_spacing;" in combined["source_text"]
    assert "col_cast_owner_fpr = (f32) col;" in combined["source_text"]
    assert "col_offset = y_spacing_owner_fpr * col_cast_owner_fpr;" in (
        combined["source_text"]
    )


def test_source_generation_includes_row_fsubs_owner_repair_candidates() -> None:
    candidate = ExpressionRepairCandidate(
        candidate_id="issue899-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )
    terminal_summary = build_terminal_summary(
        [candidate],
        ProtectedExpressionPolicy(focus_name="col_offset"),
    )

    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=terminal_summary,
        include_source=True,
        max_candidates=-1,
    )

    by_id = {
        candidate["candidate_id"]: candidate
        for candidate in generation["candidates"]
    }
    assert {
        "row-fsubs-call-result-owner",
        "row-fsubs-owner-temp",
    } <= set(by_id)
    call_owner = by_id["row-fsubs-call-result-owner"]
    assert call_owner["family"] == "row_fsubs_owner_repair"
    assert "f32 row_offset_call_owner_fpr;" in call_owner["source_text"]
    assert (
        "row_offset_call_owner_fpr = HSD_JObjGetTranslationY(jobj2);"
        in call_owner["source_text"]
    )
    assert "row_offset = row_offset_call_owner_fpr - base;" in (
        call_owner["source_text"]
    )
    owner_temp = by_id["row-fsubs-owner-temp"]
    assert "f32 row_offset_fsubs_owner_fpr;" in owner_temp["source_text"]
    assert (
        "row_offset_fsubs_owner_fpr = HSD_JObjGetTranslationY(jobj2) - base;"
        in owner_temp["source_text"]
    )
    assert "row_offset = row_offset_fsubs_owner_fpr;" in owner_temp["source_text"]
    for row in (call_owner, owner_temp):
        assert row["validation_metadata"] == {
            "requires_expression_score_validation": True,
            "known_negative_control": "row_sub_assign_split",
            "target_expression_virtual": 37,
            "expected_phys": 26,
        }


def _post_bridge_no_progress_candidates() -> list[ExpressionRepairCandidate]:
    row_col_swap = ExpressionRepairCandidate(
        candidate_id="issue900-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )
    row_fsubs_owner = ExpressionRepairCandidate(
        candidate_id="row-fsubs-owner-temp",
        expression_score=_expression_score(
            _anchor(32, "col_offset", expected=28, actual=26),
            _anchor(37, "row_offset", expected=26, actual=28),
        ),
        structural_guard={"accepted": True},
    )
    return [row_col_swap, row_fsubs_owner]


def _post_bridge_summary_for_attempted_families(
    attempted_families: list[str],
) -> dict:
    return build_terminal_summary(
        _post_bridge_no_progress_candidates(),
        ProtectedExpressionPolicy(focus_name="col_offset"),
        attempted_families=attempted_families,
    )


def _assert_source_generation_available(summary: dict) -> None:
    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=summary,
        include_source=True,
        max_candidates=-1,
    )

    assert generation["status"] == "generated"
    assert generation["candidates"]


def _assert_incomplete_post_bridge_coverage(attempted_families: list[str]) -> None:
    summary = _post_bridge_summary_for_attempted_families(attempted_families)

    assert "post_bridge_terminal_summary" not in summary
    _assert_source_generation_available(summary)


def test_attempted_route_set_does_not_synthesize_concrete_post_bridge_routes(
) -> None:
    routes = _attempted_route_set(_LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES)
    post_bridge_routes = _attempted_routes_for_post_bridge(
        _LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES
    )

    assert "non_satisfied_select_order" not in routes
    assert "non_satisfied_select_order" in post_bridge_routes


def test_terminal_summary_blocks_after_live_style_concrete_family_exhaustion(
) -> None:
    attempted_families = [
        "row_fsubs_owner_repair",
        *_LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES,
    ]

    assert "paired_row_product_recombine" not in attempted_families
    summary = _post_bridge_summary_for_attempted_families(attempted_families)

    terminal = summary["post_bridge_terminal_summary"]
    assert (
        terminal["kind"]
        == "no-expression-progress-after-row-fsubs-and-support-orders"
    )
    assert terminal["exhausted_routes"] == [
        "row_fsubs_owner_repair",
        "non_satisfied_select_order",
    ]
    assert "non_satisfied_select_order" in (
        terminal["attempted_families_normalized"]
    )
    assert "paired_row_product_recombine" not in (
        terminal["attempted_families_normalized"]
    )

    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=summary,
        include_source=True,
        max_candidates=-1,
    )

    assert generation["status"] == "blocked"
    assert generation["candidates"] == []


def test_terminal_summary_does_not_block_live_style_coverage_without_row_fsubs(
) -> None:
    _assert_incomplete_post_bridge_coverage(
        list(_LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES)
    )


def test_terminal_summary_does_not_block_live_style_coverage_without_retained(
) -> None:
    _assert_incomplete_post_bridge_coverage(
        [
            "row_fsubs_owner_repair",
            *[
                family
                for family in _LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES
                if family != "retained_fpr_case_c_target_live_range_repair"
            ],
        ]
    )


def test_terminal_summary_does_not_block_live_style_coverage_without_support_family(
) -> None:
    _assert_incomplete_post_bridge_coverage(
        [
            "row_fsubs_owner_repair",
            *[
                family
                for family in _LIVE_STYLE_POST_BRIDGE_CONCRETE_FAMILIES
                if family != "product_sink_ownership"
            ],
        ]
    )


def test_terminal_summary_does_not_block_retained_only_coverage() -> None:
    _assert_incomplete_post_bridge_coverage(
        ["retained_fpr_case_c_target_live_range_repair"]
    )


def test_terminal_summary_preserves_old_logical_route_without_concrete_coverage(
) -> None:
    summary = _post_bridge_summary_for_attempted_families(
        [
            "row-fsubs-owner-repair",
            "non-satisfied-select-order",
        ]
    )

    terminal = summary["post_bridge_terminal_summary"]
    assert terminal["exhausted_routes"] == [
        "row_fsubs_owner_repair",
        "non_satisfied_select_order",
    ]

    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=summary,
        include_source=True,
        max_candidates=-1,
    )

    assert generation["status"] == "blocked"
    assert generation["candidates"] == []


def test_terminal_summary_blocks_after_row_fsubs_and_select_order_exhaustion(
) -> None:
    row_col_swap = ExpressionRepairCandidate(
        candidate_id="issue900-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )
    row_fsubs_owner = ExpressionRepairCandidate(
        candidate_id="row-fsubs-owner-temp",
        expression_score=_expression_score(
            _anchor(32, "col_offset", expected=28, actual=26),
            _anchor(37, "row_offset", expected=26, actual=28),
        ),
        structural_guard={"accepted": True},
    )
    select_order = ExpressionRepairCandidate(
        candidate_id="select-combined-32-before-row-support",
        expression_score=_expression_score(
            _anchor(32, "col_offset", expected=28, actual=26),
            _anchor(37, "row_offset", expected=26, actual=28),
        ),
        structural_guard={"accepted": False},
        residual={
            "case": "C2",
            "ig_idx": 32,
            "baseline_reg": 26,
            "target_reg": 28,
        },
    )

    summary = build_terminal_summary(
        [row_col_swap, row_fsubs_owner, select_order],
        ProtectedExpressionPolicy(focus_name="col_offset"),
        attempted_families=[
            "row-fsubs-owner-repair",
            "non-satisfied-select-order",
            "expression-aware-source-generation",
            "sticky-pool-bridge",
        ],
    )

    assert summary["status"] == "blocked"
    terminal = summary["post_bridge_terminal_summary"]
    assert (
        terminal["kind"]
        == "no-expression-progress-after-row-fsubs-and-support-orders"
    )
    assert terminal["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    assert terminal["exhausted_routes"] == [
        "row_fsubs_owner_repair",
        "non_satisfied_select_order",
    ]

    blocker = summary["remaining_blockers"][0]
    bridge = blocker["sticky_pool_bridge"]
    assert bridge["status"] == "ready"
    assert bridge["route_status"] == "exhausted"
    assert blocker["focus"] == "col_offset"
    assert blocker["paired_source"] == "row_offset"
    assert blocker["focus_ig"] == 32
    assert blocker["paired_ig"] == 37
    assert blocker["current_focus_reg"] == 26
    assert blocker["current_paired_reg"] == 28
    assert blocker["target_reg"] == 28
    assert blocker["paired_target_reg"] == 26


def test_source_generation_blocks_instead_of_reemitting_exhausted_bridge_candidates(
) -> None:
    row_col_swap = ExpressionRepairCandidate(
        candidate_id="issue900-live-row-col-swap",
        expression_score=_expression_score(
            _anchor(
                32,
                "col_offset",
                expected=28,
                actual=26,
                expression="y_spacing * (f32) col",
                first_def_opcode="fmuls",
                first_def_operands="f32,f34,f46",
            ),
            _anchor(
                37,
                "row_offset",
                expected=26,
                actual=28,
                expression="HSD_JObjGetTranslationY(jobj2) - base",
                first_def_opcode="fsubs",
                first_def_operands="f37,f43,f38",
            ),
        ),
        structural_guard={"accepted": True},
    )
    row_fsubs_owner = ExpressionRepairCandidate(
        candidate_id="row-fsubs-owner-temp",
        expression_score=_expression_score(
            _anchor(32, "col_offset", expected=28, actual=26),
            _anchor(37, "row_offset", expected=26, actual=28),
        ),
        structural_guard={"accepted": True},
    )

    summary = build_terminal_summary(
        [row_col_swap, row_fsubs_owner],
        ProtectedExpressionPolicy(focus_name="col_offset"),
        attempted_families=[
            "row-fsubs-owner-repair",
            "non-satisfied-select-order",
            "expression-aware-source-generation",
            "sticky-pool-bridge",
        ],
    )

    generation = generate_source_repair_candidates(
        _retained_draw_cell_source(),
        function="mnDiagram_DrawCellNumber",
        terminal_summary=summary,
        include_source=True,
        max_candidates=-1,
    )

    assert generation["status"] == "blocked"
    assert generation["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    assert generation["candidates"] == []
    assert "row_fsubs_owner_repair" in generation["suppressed_families"]
    assert {
        "row-fsubs-call-result-owner",
        "row-fsubs-owner-temp",
        "row-offset-owner-split",
    }.isdisjoint(set(generation.get("candidate_ids", [])))


def test_cli_attempted_families_block_exhausted_bridge_generation(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "retained.c"
    source_path.write_text(_retained_draw_cell_source(), encoding="utf-8")
    candidate_path = tmp_path / "post_bridge_scores.json"
    candidates = [
        {
            "candidate_id": "issue900-live-row-col-swap",
            "expression_score": _expression_score(
                _anchor(
                    32,
                    "col_offset",
                    expected=28,
                    actual=26,
                    expression="y_spacing * (f32) col",
                    first_def_opcode="fmuls",
                    first_def_operands="f32,f34,f46",
                ),
                _anchor(
                    37,
                    "row_offset",
                    expected=26,
                    actual=28,
                    expression="HSD_JObjGetTranslationY(jobj2) - base",
                    first_def_opcode="fsubs",
                    first_def_operands="f37,f43,f38",
                ),
            ),
            "structural_guard": {"accepted": True},
        },
        {
            "candidate_id": "row-fsubs-call-result-owner",
            "expression_score": _expression_score(
                _anchor(32, "col_offset", expected=28, actual=26),
                _anchor(37, "row_offset", expected=26, actual=None,
                        status="missing-expression"),
            ),
            "structural_guard": {"accepted": False, "frame_delta": 8},
        },
        {
            "candidate_id": "select-combined-32-before-row-support",
            "expression_score": _expression_score(
                _anchor(32, "col_offset", expected=28, actual=26),
                _anchor(37, "row_offset", expected=26, actual=28),
            ),
            "structural_guard": {"accepted": False, "frame_delta": 8},
        },
    ]
    candidate_path.write_text(
        json.dumps({"candidates": candidates}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "expression-interferer-repair",
            "--candidate-json",
            str(candidate_path),
            "--function",
            "mnDiagram_DrawCellNumber",
            "--source-file",
            str(source_path),
            "--focus-name",
            "col_offset",
            "--attempted-families",
            (
                "row-fsubs-owner-repair,non-satisfied-select-order,"
                "expression-aware-source-generation,sticky-pool-bridge"
            ),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    terminal = summary["post_bridge_terminal_summary"]
    assert terminal["terminal_blocker"] == "current-source-shape-allocator-ceiling"
    generation = summary["source_generation"]
    assert generation["status"] == "blocked"
    assert generation["candidates"] == []
    assert "row_fsubs_owner_repair" in generation["suppressed_families"]


def test_cli_attempted_source_generation_family_suppresses_reemit_before_limit(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "retained.c"
    source_path.write_text(_retained_draw_cell_source(), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "expression-interferer-repair",
            "--function",
            "mnDiagram_DrawCellNumber",
            "--source-file",
            str(source_path),
            "--focus-name",
            "col_offset",
            "--attempted-families",
            "protected_expression_row_product_generation",
            "--max-source-candidates",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    generation = summary["source_generation"]
    assert generation["status"] == "generated"
    assert generation["candidates"]
    assert generation["candidates"][0]["candidate_id"] != "row-offset-owner-split"
    assert generation["candidates"][0]["family"] != (
        "protected_expression_row_product_generation"
    )
    assert "protected_expression_row_product_generation" in (
        generation["suppressed_families"]
    )
    assert "row-offset-owner-split" in generation["suppressed_candidate_ids"]


def test_source_generation_moves_self_scaled_row_adjust_before_mutation() -> None:
    by_id = _generation_by_id(_retained_draw_cell_source())

    candidate_text = by_id["row-scaled-adj-direct-owner"]["source_text"]
    direct_index = candidate_text.index(
        "row_offset_adj = row_offset * rowf - 0.4f;"
    )
    scale_index = candidate_text.index("row_offset *= rowf;")
    assert direct_index < scale_index


def test_source_generation_emits_row_branch_sink_owners() -> None:
    by_id = _generation_by_id(_row_product_sink_source())

    assert "row-translate-sink-owner" in by_id
    assert "row-adj-translate-sink-owner" in by_id
    assert "row-branch-sink-owner-pair" in by_id
    pair_text = by_id["row-branch-sink-owner-pair"]["source_text"]
    assert "f32 row_offset_sink_fpr;" in pair_text
    assert "f32 row_offset_adj_sink_fpr;" in pair_text
    assert "row_offset_sink_fpr = row_offset;" in pair_text
    assert "row_offset_adj_sink_fpr = row_offset_adj;" in pair_text
    assert "HSD_JObjSetTranslateY(jobj, row_offset_sink_fpr);" in pair_text
    assert "HSD_JObjSetTranslateY(jobj, row_offset_adj_sink_fpr);" in pair_text


def test_source_generation_emits_product_sink_owner() -> None:
    by_id = _generation_by_id(_row_product_sink_source())
    candidate_text = by_id["product-col-offset-sink-owner"]["source_text"]

    assert "f32 col_offset_sink_fpr;" in candidate_text
    assert "col_offset_sink_fpr = col_offset;" in candidate_text
    assert "HSD_JObjSetTranslateX(jobj, base + col_offset_sink_fpr);" in (
        candidate_text
    )
    assert "HSD_JObjSetTranslateY(jobj, row_offset);" in candidate_text
    assert "HSD_JObjSetTranslateY(jobj, row_offset_adj);" in candidate_text


def test_source_generation_emits_product_sink_owner_for_multiline_x_call() -> None:
    source = (
        _multi_line_product_sink_source()
        + "\nvoid mnDiagram_After(void* arg0) {\n"
        + "    sink(arg0);\n"
        + "}\n"
    )
    by_id = _generation_by_id(source)
    candidate_text = by_id["product-col-offset-sink-owner"]["source_text"]

    assert "f32 col_offset_sink_fpr;" in candidate_text
    assert "col_offset_sink_fpr = col_offset;" in candidate_text
    assert "HSD_JObjSetTranslateX(\n            jobj, base + col_offset_sink_fpr);" in (
        candidate_text
    )
    assert "paired-row-scaled-owner__product-sink-owner" in by_id
    assert "product_sink_ownership" in {
        candidate["family"] for candidate in by_id.values()
    }
    assert "void mnDiagram_After(void* arg0)" in candidate_text
    assert "sink(arg0);" in candidate_text


def test_source_generation_digit_guarded_motion_preserves_protected_anchors() -> None:
    by_id = _generation_by_id(_row_product_sink_source())
    original = _row_product_sink_source()
    guarded_ids = {
        "digit-guard-product-before-count",
        "digit-guard-row-scale-before-count",
        "digit-guard-product-after-row-scale",
    }

    for candidate_id in guarded_ids:
        candidate_text = by_id[candidate_id]["source_text"]
        assert candidate_text.count("digit_count = mn_GetDigitCount(") == 1
        assert candidate_text.count("HSD_JObjGetTranslationY(") == (
            original.count("HSD_JObjGetTranslationY(")
        )
        assert "if (row < 10) HSD_JObjSetTranslateY(jobj, row_offset);" in (
            candidate_text
        )
        assert "else HSD_JObjSetTranslateY(jobj, row_offset_adj);" in (
            candidate_text
        )
        assert candidate_text.count("HSD_JObjSetTranslateX(") == (
            original.count("HSD_JObjSetTranslateX(")
        )


def test_source_generation_paired_recombine_merges_non_overlapping_row_product_hunks(
) -> None:
    by_id = _generation_by_id(_row_product_sink_source())
    candidate = by_id["paired-row-scaled-owner__product-sink-owner"]
    candidate_text = candidate["source_text"]

    assert "f32 row_offset_scaled_owner_fpr;" in candidate_text
    assert "f32 col_offset_sink_fpr;" in candidate_text
    assert "row_offset_scaled_owner_fpr = row_offset * rowf;" in candidate_text
    assert "col_offset_sink_fpr = col_offset;" in candidate_text
    added_lines = [
        line
        for hunk in candidate["source_hunks"]
        for line in hunk.get("added", [])
    ]
    assert len(candidate["source_hunks"]) >= 2 or (
        "f32 row_offset_scaled_owner_fpr;" in added_lines
        and "f32 col_offset_sink_fpr;" in added_lines
    )


def test_expression_summary_retains_source_hunks_and_expression_virtuals() -> None:
    candidate = ExpressionRepairCandidate.from_payload({
        "candidate_id": "source-scored",
        "source_hunks": [{"base_start": 10, "base_end": 10, "added": ["x"]}],
        "expression_score": _expression_score(
            _anchor(32, "col_offset_product_fpr", expected=28, actual=25),
            _anchor(33, "digit_pair_f33_f34", expected=26, actual=26),
        ),
        "target_score": {"matched": 5, "virtual_distance": 1},
        "match_percent": 99.1,
        "structural_guard": {"accepted": True},
        "path": "build/diagnostics/source-scored.c",
        "score_source": {"status": "ready"},
        "checkdiff": {"accepted": True},
    })

    summary = build_terminal_summary([candidate], _policy())
    ranked = summary["ranked_candidates"][0]

    assert ranked["source_hunks"] == list(candidate.source_hunks)
    assert ranked["expression_score"]["matched"] == 1
    assert "virtuals" in ranked["expression_score"]
    assert ranked["target_score"] == {"matched": 5, "virtual_distance": 1}
    assert ranked["match_percent"] == 99.1
    assert ranked["path"] == "build/diagnostics/source-scored.c"
    assert ranked["score_source"] == {"status": "ready"}
    assert ranked["checkdiff"] == {"accepted": True}


def test_source_generation_reports_missing_row_product_shape() -> None:
    generation = generate_source_repair_candidates(
        "typedef float f32;\nvoid mnDiagram_DrawCellNumber(void) { f32 row_offset; }\n",
        function="mnDiagram_DrawCellNumber",
    )

    assert generation["status"] == "blocked"
    assert generation["reason"] == "no supported row_offset/product source anchors found"
    assert "col_offset_product_fpr product assignment" in (
        generation["missing_patterns"]
    )


def test_cli_reports_source_function_alias_miss(tmp_path: Path) -> None:
    source_path = tmp_path / "retained.c"
    source_path.write_text(
        _retained_draw_cell_source(function="mnDiagram_80241E78"),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "expression-interferer-repair",
            "--function",
            "mnDiagram_DrawCellNumber",
            "--source-file",
            str(source_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    generation = summary["source_generation"]
    assert generation["status"] == "blocked"
    assert generation["reason"] == (
        "target function mnDiagram_DrawCellNumber not found in source"
    )
    assert "--source-function" in generation["source_function_hint"]


def test_cli_can_write_expression_interferer_source_generation_probes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "retained.c"
    source_path.write_text(
        _retained_draw_cell_source(function="mnDiagram_80241E78"),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = (
        repo_root
        / "build"
        / "diagnostics"
        / f"pytest-expression-generation-{tmp_path.name}"
    )
    candidate_paths = ",".join(
        str(FIXTURE_DIR / name)
        for name in (
            "natural_5of6_case_a.json",
            "select_order_c2_regressed.json",
        )
    )

    try:
        result = runner.invoke(
            app,
            [
                "debug",
                "suggest",
                "expression-interferer-repair",
                "--candidate-json",
                candidate_paths,
                "--function",
                "mnDiagram_DrawCellNumber",
                "--source-file",
                str(source_path),
                "--source-function",
                "mnDiagram_80241E78",
                "--write-probes",
                str(out_dir),
                "--cflags-from",
                "src/melee/mn/mndiagram.c",
                "--max-source-candidates",
                "-1",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["status"] == "blocked"
        generation = summary["source_generation"]
        assert generation["status"] == "generated"
        assert generation["target_function"] == "mnDiagram_DrawCellNumber"
        assert generation["source_function"] == "mnDiagram_80241E78"
        assert generation["output_dir"] == str(out_dir)
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in generation["candidates"]
        }
        row_path = Path(by_id["row-offset-owner-split"]["path"])
        assert "row_offset_owner_fpr = row_offset;" in row_path.read_text()
        product_sink_path = Path(by_id["product-col-offset-sink-owner"]["path"])
        assert "col_offset_sink_fpr = col_offset;" in product_sink_path.read_text()
        for candidate in by_id.values():
            if "path" in candidate:
                assert candidate["score_source"]["status"] == "ready"
        score_source = by_id["row-offset-owner-split"]["score_source"]
        assert score_source["status"] == "ready"
        assert score_source["path"].startswith("build/diagnostics/")
        assert score_source["cflags_from"] == "src/melee/mn/mndiagram.c"
        assert "debug target score-source" in score_source["command"]
        assert "--checkdiff-guard" in score_source["command"]
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
