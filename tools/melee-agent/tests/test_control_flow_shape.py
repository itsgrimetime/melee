import textwrap

from src.mwcc_debug.control_flow_shape import (
    DEFAULT_CONTROL_FLOW_OPERATORS,
    generate_control_flow_shape_probes,
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
