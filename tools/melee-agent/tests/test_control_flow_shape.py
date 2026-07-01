import textwrap

import pytest

from src.mwcc_debug.control_flow_shape import (
    DEFAULT_CONTROL_FLOW_OPERATORS,
    generate_control_flow_shape_probes,
    materialize_control_flow_suggestions,
    scan_control_flow_shape_probes,
)


def _source(body: str) -> str:
    return textwrap.dedent(
        f"""\
        int fn_80000000(int cond, int a, int b)
        {{
        {body}
        }}
        """
    )


def test_default_control_flow_operators_include_local_rewrites() -> None:
    assert "ternary-to-if-else" in DEFAULT_CONTROL_FLOW_OPERATORS
    assert "if-else-to-ternary" in DEFAULT_CONTROL_FLOW_OPERATORS
    assert "bool-condition-spelling" in DEFAULT_CONTROL_FLOW_OPERATORS


def test_default_control_flow_operators_include_if_equality_switch() -> None:
    assert "if-equality-to-single-case-switch" in DEFAULT_CONTROL_FLOW_OPERATORS


def test_plain_loop_init_scan_materializes_suggestion_family_probe() -> None:
    source = _source(
        "    int i;\n"
        "    int total = 0;\n"
        "    for (i = 0; i < 4; i++) {\n"
        "        total += i;\n"
        "    }\n"
        "    return total;\n"
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("loop-init",),
    )

    assert status["blocker"] is None
    assert [probe.label for probe in probes] == [
        "loop-init-outside-for-0",
        "loop-init-renamed-counter-block-0",
    ]
    assert probes[0].operator == "loop-init"
    assert probes[0].provenance["family_id"] == "loop-init/loop-peel-unroll"
    assert "i = 0;\nfor (; i < 4; i++)" in probes[0].source_text


def _control_flow_suggestions() -> list[dict]:
    return [
        {
            "kind": "call-hoist",
            "operator": "pointer-base-call-loop",
            "evidence": {"symbol": "HSD_PadRumbleAdd"},
        },
        {
            "kind": "pointer-walk-indexed-shape",
            "operator": "pointer-walk-loop",
            "evidence": {},
        },
        {
            "kind": "loop-peel-unroll",
            "operator": "loop-init",
            "evidence": {},
        },
    ]


def _pointer_walk_source(extra_loop_body: str = "") -> str:
    return textwrap.dedent(
        f"""\
        typedef unsigned char u8;
        typedef unsigned short u16;
        typedef struct HSD_JObj HSD_JObj;
        typedef struct MnVibrationData {{
            u8 x0[6];
            HSD_JObj* jobjs[25];
        }} MnVibrationData;
        static u16 mnVibration_804D4FE8[4];
        void use(int value, HSD_JObj* jobj);

        void fn_80000000(MnVibrationData* data)
        {{
            int i;
            HSD_JObj* panel_jobj;
            for (i = 0; i < 4; i++) {{
                if (data->x0[i + 2] == 0) {{
                    panel_jobj = data->jobjs[mnVibration_804D4FE8[(u8) i]];
                    use(data->x0[i + 2], panel_jobj);
                    {extra_loop_body}
                }}
            }}
        }}
        """
    )


def _pointer_walk_index_table_helper_source() -> str:
    return textwrap.dedent(
        """\
        typedef unsigned char u8;
        void use(int value);

        static inline u8 get_visible_name(u8* sorted, int start, int rank)
        {
            u8* p;
            int idx;

            p = sorted;
            p = p + start;
            idx = start;
            p = p + 0x1C;
            while (rank > 0) {
                idx++;
                p++;
                rank--;
            }
            p = sorted;
            p += idx;
            return p[0x1C];
        }

        void fn_80000000(u8* sorted, int start, int rank)
        {
            use(get_visible_name(sorted, start, rank));
        }
        """
    )


def _pointer_walk_index_table_label_goto_source() -> str:
    return textwrap.dedent(
        """\
        typedef unsigned char u8;
        void use(int value);
        int is_visible(int value);

        void fn_80000000(u8* sorted, int cur)
        {
            u8* ptr;
            u8 result;
            int count;

            count = 7;
            ptr = sorted + cur;
            ptr = ptr + 0x1C;
        loop:
            cur++;
            ptr++;
            if (cur >= 0x78) {
                result = 0x78;
            } else if (is_visible(*ptr)) {
                count--;
                if (count <= 0) {
                    result = sorted[cur + 0x1C];
                } else {
                    goto loop;
                }
            } else {
                goto loop;
            }
            use(result);
        }
        """
    )


def _pointer_walk_index_table_target_then_helper_source() -> str:
    return textwrap.dedent(
        """\
        typedef unsigned char u8;
        void use(int value);

        static inline u8 get_visible_name(u8* sorted, int start, int rank)
        {
            u8* p;
            int idx;

            p = sorted;
            p = p + start;
            idx = start;
            p = p + 0x1C;
            while (rank > 0) {
                idx++;
                p++;
                rank--;
            }
            p = sorted;
            p += idx;
            return p[0x1C];
        }

        void fn_80000000(u8* sorted, int cur, int start, int rank)
        {
            u8* ptr;
            u8 result;

            ptr = sorted + cur;
            ptr = ptr + 0x1C;
            result = sorted[cur + 0x1C];
            use(result);
            result = sorted[start + 0x1C];
            use(result);
            use(get_visible_name(sorted, start, rank));
        }
        """
    )


def test_materialize_control_flow_suggestions_reports_family_results() -> None:
    probes, status = materialize_control_flow_suggestions(
        _pointer_walk_source(),
        "fn_80000000",
        _control_flow_suggestions(),
        max_probes_per_family=2,
    )

    families = status["families"]
    assert len(families) == 3
    assert {family["family_id"] for family in families} == {
        "pointer-base-call-loop/call-hoist",
        "pointer-walk-loop/pointer-walk-indexed-shape",
        "loop-init/loop-peel-unroll",
    }
    assert all(
        family["probe_count"] > 0 or family["terminal_proof"] is not None
        for family in families
    )
    assert probes


def test_call_hoist_materializes_return_value_temp_and_terminal_true_hoist() -> None:
    source = textwrap.dedent(
        """\
        typedef int s32;
        void HSD_PadRumbleAdd(int, int, int, int, void*);
        void fn_80000000(void)
        {
            s32 i;
            for (i = 0; i < 4; i++) {
                if (i != 2) {
                    HSD_PadRumbleAdd(i, 0, 14, 0, 0);
                    return;
                }
            }
        }
        """
    )

    probes, status = materialize_control_flow_suggestions(
        source,
        "fn_80000000",
        [_control_flow_suggestions()[0]],
        max_probes_per_family=4,
    )

    assert any("ll_probe_call_result_0" in probe.source_text for probe in probes)
    family = status["families"][0]
    proof = family["terminal_proof"]
    assert family["status"] == "materialized"
    assert proof["terminal_blocker"] == "true-hoist-not-source-preserving"
    reasons = {
        item["reason"] for item in proof["exhausted_dimensions"]
    }
    assert "loop-counter-dependent-call-args" in reasons
    assert proof["source_model_proof"]["branch_returns_after_call"] is True


def test_call_hoist_result_probes_wrap_after_prior_statement_for_c89() -> None:
    source = textwrap.dedent(
        """\
        typedef int s32;
        typedef struct HSD_JObj HSD_JObj;
        int HSD_PadRumbleAdd(int, int, int, int, void*);
        void HSD_JObjAnimAll(HSD_JObj*);
        void fn_80000000(HSD_JObj* panel_jobj2)
        {
            s32 i;
            for (i = 0; i < 4; i++) {
                if (i == 2) {
                    return;
                } else {
                    HSD_JObjAnimAll(panel_jobj2);
                    HSD_PadRumbleAdd(i, 0, 14, 0, 0);
                    return;
                }
            }
        }
        """
    )

    probes, _status = materialize_control_flow_suggestions(
        source,
        "fn_80000000",
        [_control_flow_suggestions()[0]],
        max_probes_per_family=4,
    )

    result_probes = [
        probe for probe in probes if probe.label.startswith("call-hoist-result-")
    ]
    assert [probe.label for probe in result_probes] == [
        "call-hoist-result-temp-0",
        "call-hoist-result-decl-0",
    ]
    for probe in result_probes:
        assert (
            "HSD_JObjAnimAll(panel_jobj2);\n"
            "            s32 ll_probe_call_result_"
            not in probe.source_text
        )
        assert (
            "HSD_JObjAnimAll(panel_jobj2);\n"
            "            {\n"
            "                s32 ll_probe_call_result_"
            in probe.source_text
        )
        assert (
            "            }\n"
            "            return;"
            in probe.source_text
        )
        assert probe.provenance["c89_declaration_strategy"] == (
            "local-compound-block"
        )


def test_pointer_walk_member_array_for_loop_materializes_bounded_probes() -> None:
    probes, status = materialize_control_flow_suggestions(
        _pointer_walk_source(),
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=4,
    )

    labels = {probe.label for probe in probes}
    assert "pointer-walk-member-index-table-0" in labels
    assert "pointer-walk-member-array-value-temp-0" in labels
    assert {
        probe.provenance["family_id"] for probe in probes if probe.provenance
    } == {"pointer-walk-loop/pointer-walk-indexed-shape"}
    assert status["families"][0]["probe_count"] == len(probes)

    bounded, _ = materialize_control_flow_suggestions(
        _pointer_walk_source(),
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=2,
    )
    assert len(bounded) == 2


def test_plain_pointer_walk_scan_materializes_suggestion_family_probe() -> None:
    probes, status = scan_control_flow_shape_probes(
        _pointer_walk_source(),
        "fn_80000000",
        operator_filter=("pointer-walk-loop",),
        max_probes=2,
    )

    assert status["blocker"] is None
    assert [probe.label for probe in probes] == [
        "pointer-walk-member-index-temp-0",
        "pointer-walk-member-index-table-0",
    ]
    assert probes[0].operator == "pointer-walk-loop"
    assert probes[0].provenance["family_id"] == (
        "pointer-walk-loop/pointer-walk-indexed-shape"
    )
    assert "u16 ll_probe_jobj_index_0 =" in probes[0].source_text


def test_pointer_walk_member_array_rejects_unsafe_counter_side_effect() -> None:
    source = _pointer_walk_source("i = i + 1;")

    probes, status = materialize_control_flow_suggestions(
        source,
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=4,
    )

    assert probes == []
    proof = status["families"][0]["terminal_proof"]
    assert proof["terminal_blocker"] == "unsafe-counter-side-effect"


def test_pointer_walk_index_table_helper_u8_offset_materializes() -> None:
    probes, status = materialize_control_flow_suggestions(
        _pointer_walk_index_table_helper_source(),
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=4,
    )

    assert probes
    assert status["families"][0]["status"] == "materialized"
    assert not any(
        proof.get("terminal_blocker") == "member-array-anchor-not-found"
        for proof in status["terminal_proofs"]
    )
    assert any(
        probe.label.startswith("pointer-walk-index-table-") for probe in probes
    )
    assert any(
        "sorted[idx + 0x1C]" in probe.source_text
        or "sorted + 0x1C" in probe.source_text
        or "ll_probe_" in probe.source_text
        for probe in probes
    )
    provenance = probes[0].provenance
    assert provenance["family_id"] == "pointer-walk-loop/pointer-walk-indexed-shape"
    assert provenance["owner_function"] == "get_visible_name"
    assert provenance["owner_kind"] == "static-inline-helper"
    assert provenance["byte_offset"] == "0x1C"
    assert "u8-index-table" in provenance["anchors"]


def test_pointer_walk_index_table_label_goto_target_region_materializes() -> None:
    probes, status = materialize_control_flow_suggestions(
        _pointer_walk_index_table_label_goto_source(),
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=4,
    )

    assert probes
    assert status["families"][0]["status"] == "materialized"
    assert any(
        probe.provenance["owner_function"] == "fn_80000000"
        and probe.provenance["owner_kind"] == "target-function"
        for probe in probes
    )
    assert any(
        probe.provenance["index_expr"] == "cur"
        and probe.provenance["byte_offset"] == "0x1C"
        for probe in probes
    )


def test_pointer_walk_index_table_helper_not_starved_by_target_anchors() -> None:
    probes, status = materialize_control_flow_suggestions(
        _pointer_walk_index_table_target_then_helper_source(),
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=8,
    )

    assert status["families"][0]["status"] == "materialized"
    assert any(
        probe.provenance["owner_function"] == "get_visible_name"
        and probe.provenance["anchor_kind"] == "u8-index-table-helper-return"
        for probe in probes
    )


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (
            "typedef unsigned short u16;"
            " void fn_80000000(u16* sorted, int cur)"
            " { use(sorted[cur + 0x1C]); }",
            "unsafe-non-u8-base",
        ),
        (
            "typedef unsigned char u8;"
            " void fn_80000000(u8* sorted, int cur)"
            " { use(sorted[cur++ + 0x1C]); }",
            "unsafe-index-expression",
        ),
        (
            "typedef unsigned char u8;"
            " void fn_80000000(u8* sorted, int cur, int offset)"
            " { use(sorted[cur + offset]); }",
            "nonconstant-byte-offset",
        ),
        (
            "typedef unsigned char u8;"
            " void fn_80000000(u8* sorted, int cur, u8 value)"
            " { sorted[cur + 0x1C] = value; }",
            "write-target",
        ),
        (
            "typedef unsigned char u8;"
            " void fn_80000000(u8* p) { return p[get_offset()]; }",
            "unsafe-index-expression",
        ),
        (
            "typedef unsigned char u8;"
            " void fn_80000000(u8* sorted, int cur)"
            " { sorted[cur + 0x1C]++; }",
            "write-target",
        ),
        (
            "typedef unsigned char u8;"
            " void fn_80000000(u8* sorted, int cur, int cond)"
            " { if (cond) use(sorted[cur + 0x1C]); }",
            "inline-control-flow-statement",
        ),
    ],
)
def test_pointer_walk_index_table_rejects_unsafe_byte_table_anchors(
    source: str,
    reason: str,
) -> None:
    probes, status = materialize_control_flow_suggestions(
        source,
        "fn_80000000",
        [_control_flow_suggestions()[1]],
        max_probes_per_family=4,
    )

    assert probes == []
    proof = status["families"][0]["terminal_proof"]
    assert proof["terminal_blocker"] != "member-array-anchor-not-found"
    reasons = {item["reason"] for item in proof["exhausted_dimensions"]}
    assert reason in reasons


def test_loop_init_materializes_reused_counter_init_outside_for() -> None:
    source = textwrap.dedent(
        """\
        typedef int s32;
        void use(int value);
        void fn_80000000(void)
        {
            s32 i;
            for (i = 0; i < 4; i++) {
                use(i);
            }
            for (i = 0; i < 2; i++) {
                use(i);
            }
        }
        """
    )

    probes, status = materialize_control_flow_suggestions(
        source,
        "fn_80000000",
        [_control_flow_suggestions()[2]],
        max_probes_per_family=2,
    )

    assert status["families"][0]["status"] == "materialized"
    assert any(
        "i = 0;\n    for (; i < 4; i++)" in probe.source_text
        for probe in probes
    )


def test_loop_peel_terminal_proof_names_unsafe_loop_control_flow() -> None:
    source = textwrap.dedent(
        """\
        typedef int s32;
        void fn_80000000(void)
        {
            s32 i;
            for (i = 0; i < 4; i++) {
                if (i == 2) {
                    return;
                }
            }
        }
        """
    )

    probes, status = materialize_control_flow_suggestions(
        source,
        "fn_80000000",
        [_control_flow_suggestions()[2]],
        max_probes_per_family=2,
    )

    assert probes == []
    proof = status["families"][0]["terminal_proof"]
    assert proof["terminal_blocker"] == "loop-body-control-flow"
    assert proof["exhausted_dimensions"][0]["reason"] == "loop-body-control-flow"


def test_if_equality_to_single_case_switch_rewrites_constant_rhs() -> None:
    source = _source(
        "    if (state->mode == 0x13) {\n"
        "        call_state(state);\n"
        "    }\n"
        "    return b;\n"
    ).replace(
        "int fn_80000000(int cond, int a, int b)",
        "int fn_80000000(struct State *state, int a, int b)",
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-equality-to-single-case-switch",),
    )

    assert status["blocker"] is None
    assert len(probes) == 1
    rewritten = probes[0].source_text
    assert "switch (state->mode)" in rewritten
    assert "case 0x13: {" in rewritten
    assert "call_state(state);" in rewritten
    assert "break;" in rewritten
    assert probes[0].operator == "if-equality-to-single-case-switch"


def test_if_equality_to_single_case_switch_rewrites_dereference_expression() -> None:
    source = _source(
        "    if (*state == 0x13) {\n"
        "        fn_8019B458(state);\n"
        "    }\n"
        "    return b;\n"
    ).replace(
        "int fn_80000000(int cond, int a, int b)",
        "int fn_80000000(int *state, int a, int b)",
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-equality-to-single-case-switch",),
    )

    assert status["blocker"] is None
    assert len(probes) == 1
    rewritten = probes[0].source_text
    assert "switch (*state)" in rewritten
    assert "case 0x13: {" in rewritten
    assert "fn_8019B458(state);" in rewritten


def test_if_equality_to_single_case_switch_rewrites_constant_lhs() -> None:
    source = _source(
        "    if (0x13 == state->mode) {\n"
        "        call_state(state);\n"
        "    }\n"
        "    return b;\n"
    ).replace(
        "int fn_80000000(int cond, int a, int b)",
        "int fn_80000000(struct State *state, int a, int b)",
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-equality-to-single-case-switch",),
    )

    assert status["blocker"] is None
    assert len(probes) == 1
    rewritten = probes[0].source_text
    assert "switch (state->mode)" in rewritten
    assert "case 0x13: {" in rewritten


def test_if_equality_to_single_case_switch_preserves_scope_for_declarations() -> None:
    source = _source(
        "    if (state->mode == 7) {\n"
        "        int local = a;\n"
        "        call_state(state, local);\n"
        "    }\n"
        "    return b;\n"
    ).replace(
        "int fn_80000000(int cond, int a, int b)",
        "int fn_80000000(struct State *state, int a, int b)",
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-equality-to-single-case-switch",),
    )

    assert status["blocker"] is None
    assert len(probes) == 1
    rewritten = probes[0].source_text
    case_index = rewritten.index("case 7: {")
    declaration_index = rewritten.index("int local = a;")
    break_index = rewritten.index("break;")
    assert case_index < declaration_index < break_index


def test_if_equality_to_single_case_switch_rejects_else_clause() -> None:
    source = _source(
        "    if (state->mode == 7) {\n"
        "        call_state(state);\n"
        "    } else {\n"
        "        call_other(state);\n"
        "    }\n"
        "    return b;\n"
    ).replace(
        "int fn_80000000(int cond, int a, int b)",
        "int fn_80000000(struct State *state, int a, int b)",
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-equality-to-single-case-switch",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_equality_to_single_case_switch_rejects_non_integral_comparisons() -> None:
    sources = [
        _source("    if (ptr == NULL) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(void *ptr, int a, int b)",
        ),
        _source("    if (f == 0.0f) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(float f, int a, int b)",
        ),
        _source("    if (ptr == 0) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(void *ptr, int a, int b)",
        ),
        _source("    if (f == 0) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(float f, int a, int b)",
        ),
        _source("    if (state->ptr == 0) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(struct State *state, int a, int b)",
        ),
        _source("    if (state->f == 0) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(struct State *state, int a, int b)",
        ),
        _source("    if (x == y) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(int x, int y, int b)",
        ),
        _source(
            '    if (state->name == "run") {\n'
            "        return a;\n"
            "    }\n"
            "    return b;\n"
        ).replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(struct State *state, int a, int b)",
        ),
    ]

    for source in sources:
        probes, status = scan_control_flow_shape_probes(
            source,
            "fn_80000000",
            operator_filter=("if-equality-to-single-case-switch",),
        )

        assert probes == []
        assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_equality_to_single_case_switch_rejects_side_effectful_dereferences() -> None:
    sources = [
        _source("    if (*state++ == 0x13) {\n        return a;\n    }\n    return b;\n").replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(int *state, int a, int b)",
        ),
        _source("    if (*poll() == 0x13) {\n        return a;\n    }\n    return b;\n"),
    ]

    for source in sources:
        probes, status = scan_control_flow_shape_probes(
            source,
            "fn_80000000",
            operator_filter=("if-equality-to-single-case-switch",),
        )

        assert probes == []
        assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_equality_to_single_case_switch_rejects_preprocessor_touched_regions() -> None:
    source = _source(
        "    if (state->mode == 7) {\n"
        "#if 1\n"
        "        call_state(state);\n"
        "#endif\n"
        "    }\n"
        "    return b;\n"
    ).replace(
        "int fn_80000000(int cond, int a, int b)",
        "int fn_80000000(struct State *state, int a, int b)",
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-equality-to-single-case-switch",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_equality_to_single_case_switch_rejects_moved_body_control_flow() -> None:
    unsafe_bodies = [
        "label:\n        call_state(state);",
        "break;",
        "continue;",
        "goto label;",
        "switch (a) {\n        case 1:\n            call_state(state);\n        }",
        "switch (a) {\n        default:\n            call_state(state);\n        }",
    ]

    for unsafe_body in unsafe_bodies:
        source = _source(
            "    if (state->mode == 7) {\n"
            f"        {unsafe_body}\n"
            "    }\n"
            "    return b;\n"
        ).replace(
            "int fn_80000000(int cond, int a, int b)",
            "int fn_80000000(struct State *state, int a, int b)",
        )

        probes, status = scan_control_flow_shape_probes(
            source,
            "fn_80000000",
            operator_filter=("if-equality-to-single-case-switch",),
        )

        assert probes == []
        assert status["blocker"] == "no-control-flow-shape-probes"


def test_ternary_assignment_expands_to_if_else() -> None:
    source = _source("    int x;\n    x = cond ? a : b;\n    return x;\n")

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("ternary-to-if-else",),
    )

    assert status["blocker"] is None
    assert len(probes) == 1
    rewritten = probes[0].source_text
    assert "    if (cond) {\n        x = a;\n    } else {\n        x = b;\n    }" in rewritten
    assert probes[0].operator == "ternary-to-if-else"
    assert probes[0].provenance["kind"] == "control-flow-shape"


def test_if_else_assignment_collapses_to_ternary() -> None:
    source = _source(
        "    int x;\n"
        "    if (cond) {\n"
        "        x = a;\n"
        "    } else {\n"
        "        x = b;\n"
        "    }\n"
        "    return x;\n"
    )

    probes = generate_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-else-to-ternary",),
    )

    assert len(probes) == 1
    assert "    x = cond ? a : b;\n" in probes[0].source_text
    assert probes[0].operator == "if-else-to-ternary"


def test_boolean_condition_spelling_generates_safe_alternative() -> None:
    source = _source("    if (!cond) {\n        return a;\n    }\n    return b;\n")

    probes = generate_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("bool-condition-spelling",),
    )

    assert len(probes) == 1
    assert "if (cond == 0)" in probes[0].source_text
    assert probes[0].operator == "bool-condition-spelling"


def test_boolean_condition_spelling_collapses_zero_comparison() -> None:
    source = _source("    if (cond == 0) {\n        return a;\n    }\n    return b;\n")

    probes = generate_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("bool-condition-spelling",),
    )

    assert len(probes) == 1
    assert "if (!cond)" in probes[0].source_text
    assert probes[0].operator == "bool-condition-spelling"


def test_boolean_condition_spelling_collapses_nonzero_member_comparison() -> None:
    source = _source(
        "    if (state->flag != 0) {\n        return a;\n    }\n    return b;\n"
    )

    probes = generate_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("bool-condition-spelling",),
    )

    assert len(probes) == 1
    assert "if (state->flag)" in probes[0].source_text
    assert probes[0].operator == "bool-condition-spelling"


def test_boolean_condition_spelling_rejects_side_effectful_call() -> None:
    source = _source("    if (poll()) {\n        return a;\n    }\n    return b;\n")

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("bool-condition-spelling",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_boolean_condition_spelling_rejects_non_simple_negation() -> None:
    source = _source("    if (!cond + a) {\n        return a;\n    }\n    return b;\n")

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("bool-condition-spelling",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_delegates_existing_pressure_explorer_operator() -> None:
    source = _source("    if (cond && a) {\n        return b;\n    }\n    return a;\n")

    probes = generate_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("condition-nesting",),
    )

    assert len(probes) == 1
    assert probes[0].operator == "condition-nesting"
    assert "if (cond) {" in probes[0].source_text
    assert "if (a)" in probes[0].source_text


def test_comments_and_strings_are_ignored() -> None:
    source = _source(
        '    char *text = "x = cond ? a : b;";\n'
        "    /* x = cond ? a : b; */\n"
        "    return a;\n"
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("ternary-to-if-else",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_unknown_operator_reports_unsupported_control_flow_shape() -> None:
    probes, status = scan_control_flow_shape_probes(
        _source("    return a;\n"),
        "fn_80000000",
        operator_filter=("not-a-real-operator",),
    )

    assert probes == []
    assert status["blocker"] == "unsupported-control-flow-shape"


def test_local_rewrites_reject_unsafe_expressions() -> None:
    unsafe_bodies = [
        "    out[i++] = cond ? a : b;\n    return a;\n",
        "    set_out() = cond ? a : b;\n    return a;\n",
        "    a, x = cond ? a : b;\n    return x;\n",
        "    x = (cond = a) ? a : b;\n    return x;\n",
        "    x = cond ? a++, b : b;\n    return x;\n",
    ]

    for body in unsafe_bodies:
        probes, status = scan_control_flow_shape_probes(
            _source("    int x;\n" + body),
            "fn_80000000",
            operator_filter=("ternary-to-if-else",),
        )
        assert probes == []
        assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_else_to_ternary_rejects_nested_control_flow_and_labels() -> None:
    source = _source(
        "    int x;\n"
        "label:\n"
        "    if (cond) {\n"
        "        if (a) { x = a; }\n"
        "    } else {\n"
        "        x = b;\n"
        "    }\n"
        "    return x;\n"
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-else-to-ternary",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_else_to_ternary_rejects_compound_assignment() -> None:
    source = _source(
        "    int x;\n"
        "    if (cond) {\n"
        "        x += a;\n"
        "    } else {\n"
        "        x += b;\n"
        "    }\n"
        "    return x;\n"
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("if-else-to-ternary",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_if_else_to_ternary_rejects_nested_assignment_expression_statement() -> None:
    unsafe_true_statements = [
        "        a, x = a;\n",
        "        a && (x = a);\n",
    ]

    for true_statement in unsafe_true_statements:
        source = _source(
            "    int x;\n"
            "    if (cond) {\n"
            f"{true_statement}"
            "    } else {\n"
            "        x = b;\n"
            "    }\n"
            "    return x;\n"
        )

        probes, status = scan_control_flow_shape_probes(
            source,
            "fn_80000000",
            operator_filter=("if-else-to-ternary",),
        )

        assert probes == []
        assert status["blocker"] == "no-control-flow-shape-probes"


def test_local_rewrites_ignore_preprocessor_regions() -> None:
    source = _source(
        "    int x;\n"
        "#if 1\n"
        "    x = cond ? a : b;\n"
        "#endif\n"
        "    return x;\n"
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("ternary-to-if-else",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"


def test_local_rewrites_ignore_preprocessor_region_at_file_start() -> None:
    source = textwrap.dedent(
        """\
        #if 1
        int fn_80000000(int cond, int a, int b)
        {
            int x;
            x = cond ? a : b;
            return x;
        }
        #endif
        """
    )

    probes, status = scan_control_flow_shape_probes(
        source,
        "fn_80000000",
        operator_filter=("ternary-to-if-else",),
    )

    assert probes == []
    assert status["blocker"] == "no-control-flow-shape-probes"
