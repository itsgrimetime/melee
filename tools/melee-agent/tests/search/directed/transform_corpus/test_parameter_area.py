"""Tests for the parameter_area transform family (transform_corpus.parameter_area)."""
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


def test_generate_transform_probes_materializes_outgoing_parameter_area_calls() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(int i, f32 divider, char* name_str) {\n"
        "    HSD_Text* icon_text;\n"
        "    f32 x;\n"
        "    f32 y;\n"
        "    icon_text = HSD_SisLib_803A5ACC(\n"
        "        0, 1, x + y,\n"
        "        y * (f32) i / divider, x,\n"
        "        divider, divider);\n"
        "    HSD_SisLib_803A6B98(icon_text, x, y, name_str);\n"
        "    HSD_SisLib_803A6B98(icon_text, x + y, y, name_str);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/demo",
        force_phys={},
        families=("outgoing_parameter_area_shape",),
        max_per_family=8,
    )

    probes = tuple(
        probe for probe in probes
        if probe.family_id == "outgoing_parameter_area_shape"
    )
    assert probes
    assert {
        probe.mutator_key for probe in probes
    } == {"materialize_outgoing_parameter_area_call_args"}
    modes = {probe.payload["mode"] for probe in probes}
    assert {"call-site", "same-callee-batch"} <= modes

    assignment_probe = next(
        probe for probe in probes
        if probe.payload["mode"] == "call-site"
        and probe.payload["callee"] == "HSD_SisLib_803A5ACC"
    )
    assert assignment_probe.payload["argument_count"] == 7
    assert assignment_probe.payload["tempized_argument_indices"][:2] == [2, 3]
    assert "f32 param_area_0_2 = x + y;" in assignment_probe.candidate_text
    assert (
        "f32 param_area_0_3 = y * (f32) i / divider;"
        in assignment_probe.candidate_text
    )
    assert "0, 1, param_area_0_2," in assignment_probe.candidate_text
    assert "param_area_0_3, param_area_0_4," in assignment_probe.candidate_text

    batch_probe = next(
        probe for probe in probes
        if probe.payload["mode"] == "same-callee-batch"
        and probe.payload["callee"] == "HSD_SisLib_803A6B98"
    )
    assert batch_probe.payload["call_site_count"] == 2
    assert "f32 param_area_1_1 = x;" in batch_probe.candidate_text
    assert "char* param_area_1_3 = name_str;" in batch_probe.candidate_text
    assert "f32 param_area_2_1 = x + y;" in batch_probe.candidate_text
    assert (
        "HSD_SisLib_803A6B98(icon_text, param_area_1_1, "
        "param_area_1_2, param_area_1_3);"
    ) in batch_probe.candidate_text


def test_generate_transform_probes_dematerializes_one_use_parameter_area_temps() -> None:
    source = (
        "void target(int i, f32 divider, char* name_str) {\n"
        "    HSD_Text* text;\n"
        "    f32 y;\n"
        "    {\n"
        "        f32 f1 = 1.0F;\n"
        "        f32 offset_y = y * (f32) i / divider;\n"
        "        HSD_SisLib_803A6B98(text, f1, offset_y, name_str);\n"
        "    }\n"
        "    {\n"
        "        f32 f1 = 2.0F;\n"
        "        f32 offset_y = y + divider;\n"
        "        HSD_SisLib_803A6B98(text, f1, offset_y, name_str);\n"
        "    }\n"
        "}\n"
    )

    probes = [
        probe for probe in generate_transform_probes(
            source,
            function="target",
            unit="melee/demo",
            force_phys={},
            families=("outgoing_parameter_area_shape",),
            max_per_family=8,
        )
        if probe.family_id == "outgoing_parameter_area_shape"
    ]

    dematerialize = next(
        probe for probe in probes
        if probe.payload["mode"] == "call-site-dematerialize"
    )
    assert dematerialize.payload["callee"] == "HSD_SisLib_803A6B98"
    assert dematerialize.payload["dematerialized_locals"] == ["f1", "offset_y"]
    assert "f32 f1 = 1.0F;" not in dematerialize.candidate_text
    assert "f32 offset_y = y * (f32) i / divider;" not in dematerialize.candidate_text
    assert (
        "HSD_SisLib_803A6B98(text, 1.0F, y * (f32) i / divider, name_str);"
        in dematerialize.candidate_text
    )

    batch = next(
        probe for probe in probes
        if probe.payload["mode"] == "same-callee-dematerialize-batch"
    )
    assert batch.payload["callee"] == "HSD_SisLib_803A6B98"
    assert batch.payload["call_site_count"] == 2
    assert "f32 f1 = 1.0F;" not in batch.candidate_text
    assert "f32 f1 = 2.0F;" not in batch.candidate_text
    assert "HSD_SisLib_803A6B98(text, 2.0F, y + divider, name_str);" in (
        batch.candidate_text
    )


def test_outgoing_parameter_area_shape_rejects_nested_call_arguments() -> None:
    source = (
        "void target(int i, f32 divider) {\n"
        "    f32 x;\n"
        "    HSD_SisLib_803A5ACC(0, 1, helper(x), x, divider, divider, divider);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/demo",
        force_phys={},
        families=("outgoing_parameter_area_shape",),
        max_per_family=8,
    )

    assert "outgoing_parameter_area_shape" not in {probe.family_id for probe in probes}
