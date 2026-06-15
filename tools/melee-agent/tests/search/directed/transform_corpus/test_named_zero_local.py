"""Tests for the named_zero_local transform family (transform_corpus.named_zero_local)."""
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


def test_generate_transform_probes_introduces_named_null_local() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(void) {\n"
        "    int i;\n"
        "    HSD_Text* labels[3];\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        if (labels[i] != NULL) {\n"
        "            free_text(labels[i]);\n"
        "            labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes if probe.family_id == "named_zero_local_shape"
    )
    assert probe.mutator_key == "introduce_named_zero_local"
    assert "    HSD_Text* labels_null = NULL;\n    int i;" in probe.candidate_text
    assert "if (labels[i] != NULL)" in probe.candidate_text
    assert "labels[i] = labels_null;" in probe.candidate_text
    assert probe.payload["zero_name"] == "labels_null"
    assert probe.payload["zero_type"] == "HSD_Text*"
    assert probe.payload["proof_source"] == "if-null-check-assignment-pair"


def test_generate_transform_probes_introduces_named_null_local_for_struct_field_array() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "typedef struct MnCountData { HSD_Text* labels[3]; } MnCountData;\n"
        "void target(MnCountData* userdata2, MnCountData* userdata3) {\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        if (userdata2->labels[i] != NULL) {\n"
        "            free_text(userdata3->labels[i]);\n"
        "            userdata2->labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes if probe.family_id == "named_zero_local_shape"
    )
    assert "HSD_Text* labels_null = NULL;" in probe.candidate_text
    assert "if (userdata2->labels[i] != NULL)" in probe.candidate_text
    assert "userdata2->labels[i] = labels_null;" in probe.candidate_text
    assert probe.payload["expr"] == "userdata2->labels[i]"


def test_generate_transform_probes_named_null_rejects_name_collision() -> None:
    source = (
        "void target(void) {\n"
        "    void* labels_null = NULL;\n"
        "    if (data->labels[i] != NULL) {\n"
        "        data->labels[i] = NULL;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_named_null_rejects_parameter_collision() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(HSD_Text* labels_null) {\n"
        "    HSD_Text* labels[3];\n"
        "    if (labels[i] != NULL) {\n"
        "        labels[i] = NULL;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_named_null_rejects_untyped_or_integer_null() -> None:
    source = (
        "void target(void) {\n"
        "    int field;\n"
        "    if (field != NULL) {\n"
        "        field = NULL;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_named_null_rejects_out_of_scope_type_proof() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(void) {\n"
        "    {\n"
        "        HSD_Text* labels[3];\n"
        "    }\n"
        "    if (labels[i] != NULL) {\n"
        "        labels[i] = NULL;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_named_null_rejects_shadowed_pointer_proof() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(void) {\n"
        "    HSD_Text* labels[3];\n"
        "    {\n"
        "        int labels[3];\n"
        "        if (labels[i] != NULL) {\n"
        "            labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_named_null_rejects_comma_decl_shadow() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(void) {\n"
        "    HSD_Text* labels[3];\n"
        "    {\n"
        "        int j, labels[3];\n"
        "        if (labels[i] != NULL) {\n"
        "            labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_named_null_rejects_commented_shadow_decl() -> None:
    source = (
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(void) {\n"
        "    HSD_Text* labels[3];\n"
        "    {\n"
        "        int labels[3]; // shadows the outer pointer array\n"
        "        if (labels[i] != NULL) {\n"
        "            labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={},
        families=("named_zero_local_shape",),
        max_per_family=2,
    )

    assert "named_zero_local_shape" not in {probe.family_id for probe in probes}
