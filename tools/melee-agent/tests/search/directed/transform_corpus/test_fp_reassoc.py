"""Tests for the fp_reassoc transform family (transform_corpus.fp_reassoc)."""
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


def test_generate_transform_probes_reassociates_unary_fp_subtraction_literal() -> None:
    source = (
        "typedef float f32;\n"
        "f32 HSD_JObjGetTranslationY(void* jobj);\n"
        "void target(void) {\n"
        "    pos.y = -HSD_JObjGetTranslationY(jobj) - 0.5f;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("fp_subtraction_operand_reassociation",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes
        if probe.family_id == "fp_subtraction_operand_reassociation"
    )
    assert probe.mutator_key == "reassociate_fp_subtraction_operands"
    assert "pos.y = -0.5f - HSD_JObjGetTranslationY(jobj);" in probe.candidate_text
    assert probe.payload["span_text"] == "-HSD_JObjGetTranslationY(jobj) - 0.5f"
    assert probe.payload["replacement_text"] == "-0.5f - HSD_JObjGetTranslationY(jobj)"
    assert probe.payload["target_function"] == "target"


def test_generate_transform_probes_reassociates_bare_return_fp_subtraction() -> None:
    source = (
        "typedef float f32;\n"
        "f32 target(f32 height) {\n"
        "    return -height - 0.5f;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("fp_subtraction_operand_reassociation",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes
        if probe.family_id == "fp_subtraction_operand_reassociation"
    )
    assert "return -0.5f - height;" in probe.candidate_text


def test_generate_transform_probes_reassociates_call_argument_fp_subtraction() -> None:
    source = (
        "void target(void) {\n"
        "    draw_text(ctx, -spEC.y - 0.9f, scale);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("fp_subtraction_operand_reassociation",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes
        if probe.family_id == "fp_subtraction_operand_reassociation"
    )
    assert "draw_text(ctx, -0.9f - spEC.y, scale);" in probe.candidate_text
    assert probe.payload["span_text"] == "-spEC.y - 0.9f"


@pytest.mark.parametrize(
    "source",
    (
        (
            "void target(void) {\n"
            "    pos.y = neg_spacing * fi + -sp48.y;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    pos.y = a + -b - 0.5f;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    pos.y = a * -b - 0.5f;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    pos.y = value - 0.5f;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    pos.y = lhs - rhs;\n"
            "}\n"
        ),
        (
            "typedef long s32;\n"
            "void target(s32 count) {\n"
            "    pos.y = -count - 0.5f;\n"
            "}\n"
        ),
    ),
)
def test_generate_transform_probes_rejects_non_equivalent_fp_subtraction_forms(
    source: str,
) -> None:
    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("fp_subtraction_operand_reassociation",),
        max_per_family=2,
    )

    assert "fp_subtraction_operand_reassociation" not in {
        probe.family_id for probe in probes
    }
