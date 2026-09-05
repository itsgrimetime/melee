"""Tests for the contract_signature transform family (transform_corpus.contract_signature)."""
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


def test_generate_transform_probes_removes_unused_trailing_parameter_contract() -> None:
    source = (
        "static int helper(int value, int unused);\n"
        "\n"
        "static int helper(int value, int unused) {\n"
        "    return value + 1;\n"
        "}\n"
        "\n"
        "int target(int x) {\n"
        "    int a = helper(x + 1, 0);\n"
        "    int b = helper(helper(x, 0), 0);\n"
        "    int c = helper(x, 0), d = helper(x + 2, 0);\n"
        "    return a + b + c + d;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="helper",
        unit="melee/demo",
        force_phys={1: 3},
        families=("unused_trailing_parameter",),
        max_per_family=4,
    )

    probe = next(
        probe
        for probe in probes
        if probe.mutator_key == "remove_unused_trailing_parameter"
    )
    assert probe.payload["requires_full_unit_source"] is True
    assert probe.payload["parameter_name"] == "unused"
    assert probe.payload["parameter_type"] == "int"
    assert probe.payload["parameter_index"] == 1
    assert len(probe.payload["updated_call_sites"]) == 5
    assert "static int helper(int value);\n" in probe.candidate_text
    assert "static int helper(int value) {\n" in probe.candidate_text
    assert "helper(x + 1)" in probe.candidate_text
    assert "helper(helper(x))" in probe.candidate_text
    assert "helper(x), d = helper(x + 2)" in probe.candidate_text
    assert "unused" not in probe.candidate_text


def test_generate_transform_probes_adds_void_to_trailing_parameter_contract() -> None:
    source = (
        "static int helper(void);\n"
        "\n"
        "static int helper(void) {\n"
        "    return 1;\n"
        "}\n"
        "\n"
        "int target(void) {\n"
        "    return helper() + helper();\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="helper",
        unit="melee/demo",
        force_phys={1: 3},
        families=("unused_trailing_parameter",),
        max_per_family=4,
    )

    probe = next(
        probe
        for probe in probes
        if probe.mutator_key == "add_unused_trailing_parameter"
    )
    assert probe.payload["requires_full_unit_source"] is True
    assert probe.payload["parameter_name"] == "unused"
    assert probe.payload["parameter_type"] == "int"
    assert probe.payload["parameter_index"] == 0
    assert len(probe.payload["updated_call_sites"]) == 2
    assert "static int helper(int unused);\n" in probe.candidate_text
    assert "static int helper(int unused) {\n" in probe.candidate_text
    assert "return helper(0) + helper(0);" in probe.candidate_text


def test_unused_trailing_parameter_rejects_nonstatic_or_address_taken_contracts() -> None:
    nonstatic = (
        "int helper(int value, int unused);\n"
        "int helper(int value, int unused) {\n"
        "    return value;\n"
        "}\n"
        "int target(void) { return helper(1, 0); }\n"
    )
    address_taken = (
        "static int helper(int value, int unused) {\n"
        "    return value;\n"
        "}\n"
        "int (*helper_table[])(int, int) = { helper };\n"
        "int target(void) { return helper(1, 0); }\n"
    )

    for source in (nonstatic, address_taken):
        probes = generate_transform_probes(
            source,
            function="helper",
            unit="melee/demo",
            force_phys={1: 3},
            families=("unused_trailing_parameter",),
        )
        assert "unused_trailing_parameter" not in {probe.family_id for probe in probes}


def test_unused_trailing_parameter_rejects_preprocessor_hidden_call_contracts() -> None:
    source = (
        "static int helper(int value, int unused) {\n"
        "    return value;\n"
        "}\n"
        "#if 0\n"
        "int disabled(void) { return helper(1, 0); }\n"
        "#endif\n"
        "int target(void) { return helper(1, 0); }\n"
    )

    probes = generate_transform_probes(
        source,
        function="helper",
        unit="melee/demo",
        force_phys={1: 3},
        families=("unused_trailing_parameter",),
    )

    assert "unused_trailing_parameter" not in {probe.family_id for probe in probes}


def test_unused_trailing_parameter_rejects_macro_mediated_parameter_use() -> None:
    source = (
        "#define USE() unused\n"
        "static int helper(int value, int unused) {\n"
        "    return value + USE();\n"
        "}\n"
        "int target(void) { return helper(1, 0); }\n"
    )

    probes = generate_transform_probes(
        source,
        function="helper",
        unit="melee/demo",
        force_phys={1: 3},
        families=("unused_trailing_parameter",),
    )

    assert "unused_trailing_parameter" not in {probe.family_id for probe in probes}
