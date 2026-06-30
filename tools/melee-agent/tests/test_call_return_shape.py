"""Tests for call-return copy-propagation source-shape probes."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.call_return_shape import (
    CALL_RETURN_USE_SHAPE_OPERATOR,
    generate_call_return_use_shape_probes,
    summarize_call_return_use_shape_trace,
)


def _trace_target() -> dict:
    origin = {
        "source_file": "src/melee/mn/demo.c",
        "source_line": 11,
        "expression": "GetNameText(post_ceiling_j_name)",
        "assigned_local": "post_ceiling_j_text",
    }
    return {
        "register_class": "gpr",
        "first_absent_pass": "AFTER COPY PROPAGATION",
        "from_virtual": 64,
        "to_virtual": 34,
        "from_operand": {
            "token": "r64",
            "expression": "GetNameText(post_ceiling_j_name)",
            "mapped_to_source": True,
            "call_return_origin": origin,
        },
        "to_operand": {
            "token": "r34",
            "expression": "GetNameText(post_ceiling_j_name)",
            "mapped_to_source": True,
            "call_return_origin": origin,
        },
    }


def _source() -> str:
    return textwrap.dedent("""\
        char* GetNameText(unsigned char value);

        void mnDiagram_SortNamesByKOs(void)
        {
            unsigned char post_ceiling_j_name;
            char* post_ceiling_j_text;
            char* post_ceiling_j_text_copy;
            post_ceiling_j_text = GetNameText(post_ceiling_j_name);
            post_ceiling_j_text_copy = post_ceiling_j_text;
            if ((post_ceiling_j_text_copy != 0) &&
                (post_ceiling_j_text_copy != 0)) {
                sink();
            }
        }
    """)


def test_generate_call_return_use_shape_probes_emits_c89_valid_families() -> None:
    probes = generate_call_return_use_shape_probes(
        _source(),
        "mnDiagram_SortNamesByKOs",
        _trace_target(),
        max_probes=8,
    )

    variants = {probe.provenance["variant"]: probe for probe in probes}
    assert {probe.operator for probe in probes} == {CALL_RETURN_USE_SHAPE_OPERATOR}
    assert {
        "direct-use",
        "direct-first-use",
        "duplicate-call",
        "declaration-initializer",
        "scoped-copy",
    } <= set(variants)
    assert "post_ceiling_j_text_copy = post_ceiling_j_text;\n" not in (
        variants["direct-use"].source_text
    )
    assert "post_ceiling_j_text_copy = GetNameText(post_ceiling_j_name);" in (
        variants["duplicate-call"].source_text
    )
    assert "char* post_ceiling_j_text_copy = GetNameText(post_ceiling_j_name);" in (
        variants["declaration-initializer"].source_text
    )
    scoped = variants["scoped-copy"].source_text
    assert "{\n        char* ll_callret_copy_0 = post_ceiling_j_text;" in scoped
    assert all(probe.provenance["copy_local"] == "post_ceiling_j_text_copy" for probe in probes)
    assert all(probe.provenance["assigned_local"] == "post_ceiling_j_text" for probe in probes)


def test_generate_call_return_use_shape_probes_requires_source_mapped_call_return() -> None:
    trace = _trace_target()
    trace["from_operand"] = {"token": "r64", "mapped_to_source": False}
    trace["to_operand"] = {"token": "r34", "mapped_to_source": False}

    assert not generate_call_return_use_shape_probes(
        _source(),
        "mnDiagram_SortNamesByKOs",
        trace,
        max_probes=8,
    )


def test_summarize_call_return_use_shape_trace_names_next_retained_command() -> None:
    summary = summarize_call_return_use_shape_trace(
        _trace_target(),
        function="mnDiagram_SortNamesByKOs",
    )

    assert summary is not None
    assert summary["kind"] == "call-return-use-shape-continuation"
    assert summary["status"] == "source-shape-probe-required"
    assert summary["target_pair"] == "r64/r34"
    assert summary["source_expression"] == "GetNameText(post_ceiling_j_name)"
    assert summary["assigned_local"] == "post_ceiling_j_text"
    assert "declaration-initializer" in summary["candidate_families"]
    assert "debug coalesce-search" in summary["next_command"]
    assert "-f mnDiagram_SortNamesByKOs" in summary["next_command"]
