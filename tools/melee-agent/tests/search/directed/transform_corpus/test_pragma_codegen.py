"""Tests for the pragma_codegen transform family (transform_corpus.pragma_codegen)."""
from __future__ import annotations

import pytest

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probes,
    plan_transform_experiments,
)
from src.search.directed.transform_probe_adapter import transform_probe_key
from src.mwcc_debug.source_shape import CandidatePatch


def _pragma_shape_probes(source: str, *, max_per_family: int = 3):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("function_codegen_pragma_shape",),
        max_per_family=max_per_family,
    )


def test_function_codegen_pragma_shape_adds_dont_inline_wrapper() -> None:
    source = (
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}\n"
    )

    probes = _pragma_shape_probes(source, max_per_family=2)

    add_probe = next(
        probe
        for probe in probes
        if probe.mutator_key == "add_dont_inline_pragma_pair"
    )
    assert add_probe.family_id == "function_codegen_pragma_shape"
    assert add_probe.probe_id == "function_codegen_pragma_shape@0"
    assert add_probe.candidate_text == (
        "#pragma push\n"
        "#pragma dont_inline on\n"
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "#pragma pop\n"
    )
    assert add_probe.payload["pragma_kind"] == "dont_inline"
    assert add_probe.payload["mode"] == "add"
    assert add_probe.payload["target_function"] == "target"


def test_function_codegen_pragma_shape_adds_newline_before_pop_at_eof() -> None:
    source = (
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}"
    )

    probes = _pragma_shape_probes(source, max_per_family=2)

    add_probe = next(
        probe
        for probe in probes
        if probe.mutator_key == "add_dont_inline_pragma_pair"
    )
    assert add_probe.candidate_text == (
        "#pragma push\n"
        "#pragma dont_inline on\n"
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "#pragma pop\n"
    )


def test_function_codegen_pragma_shape_removes_exact_dont_inline_wrapper() -> None:
    source = (
        "#pragma push\n"
        "#pragma dont_inline on\n"
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "#pragma pop\n"
    )

    probes = _pragma_shape_probes(source, max_per_family=2)

    remove_probe = next(
        probe
        for probe in probes
        if probe.mutator_key == "remove_dont_inline_pragma_pair"
    )
    assert remove_probe.family_id == "function_codegen_pragma_shape"
    assert remove_probe.candidate_text == (
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}\n"
    )
    assert remove_probe.payload["pragma_kind"] == "dont_inline"
    assert remove_probe.payload["mode"] == "remove"
    assert remove_probe.payload["target_function"] == "target"


def test_function_codegen_pragma_shape_rejects_mixed_pragma_wrapper_removal() -> None:
    source = (
        "#pragma push\n"
        "#pragma dont_inline on\n"
        "#pragma scheduling off\n"
        "bool target(HSD_GObj* gobj)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "#pragma pop\n"
    )

    probes = _pragma_shape_probes(source, max_per_family=2)

    assert "function_codegen_pragma_shape" not in {
        probe.family_id for probe in probes
    }


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "preprocessor body",
            (
                "bool target(HSD_GObj* gobj)\n"
                "{\n"
                "#if 1\n"
                "    return false;\n"
                "#endif\n"
                "}\n"
            ),
        ),
        (
            "existing adjacent pragma",
            (
                "#pragma scheduling off\n"
                "bool target(HSD_GObj* gobj)\n"
                "{\n"
                "    return false;\n"
                "}\n"
            ),
        ),
        (
            "label in body",
            (
                "bool target(HSD_GObj* gobj)\n"
                "{\n"
                "again:\n"
                "    return false;\n"
                "}\n"
            ),
        ),
        (
            "case in body",
            (
                "bool target(int kind)\n"
                "{\n"
                "    switch (kind) {\n"
                "    case 0:\n"
                "        return false;\n"
                "    }\n"
                "    return true;\n"
                "}\n"
            ),
        ),
        (
            "oversized body",
            (
                "bool target(HSD_GObj* gobj)\n"
                "{\n"
                "    step0();\n"
                "    step1();\n"
                "    step2();\n"
                "    step3();\n"
                "    step4();\n"
                "    step5();\n"
                "    step6();\n"
                "    step7();\n"
                "    step8();\n"
                "    return false;\n"
                "}\n"
            ),
        ),
    ),
)
def test_function_codegen_pragma_shape_rejects_unsafe_add_cases(
    case: str, source: str
) -> None:
    probes = _pragma_shape_probes(source, max_per_family=2)

    assert "function_codegen_pragma_shape" not in {probe.family_id for probe in probes}, case
