"""Tests for the statement_order transform family (transform_corpus.statement_order)."""
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


def _statement_order_probes(source: str, *, max_per_family: int = 3):
    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/order",
        force_phys={1: 3},
        families=("independent_statement_order",),
        max_per_family=max_per_family,
    )
    return tuple(
        probe for probe in probes
        if probe.family_id == "independent_statement_order"
    )


def test_generate_transform_probes_materializes_independent_statement_swap() -> None:
    source = (
        "void target(void) {\n"
        "    s32 a;\n"
        "    s32 b;\n"
        "    s32 x;\n"
        "    s32 y;\n"
        "    a = x + 1;\n"
        "    b = y + 2;\n"
        "}\n"
    )

    probes = _statement_order_probes(source, max_per_family=1)

    assert len(probes) == 1
    probe = probes[0]
    assert probe.family_id == "independent_statement_order"
    assert probe.mutator_key == "swap_independent_adjacent_statements"
    assert "    b = y + 2;\n    a = x + 1;\n" in probe.candidate_text
    assert probe.payload["movement"] == "swap-adjacent"
    assert probe.payload["first_writes"] == ["a"]
    assert probe.payload["first_reads"] == ["x"]
    assert probe.payload["second_writes"] == ["b"]
    assert probe.payload["second_reads"] == ["y"]


@pytest.mark.parametrize(
    "source",
    (
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 x;\n"
            "    a = b;\n"
            "    b = x;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 x;\n"
            "    a = x;\n"
            "    b = a;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 x;\n"
            "    s32 y;\n"
            "    a = x;\n"
            "    a = y;\n"
            "}\n"
        ),
        (
            "s32 global_value;\n"
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 y;\n"
            "    a = global_value;\n"
            "    b = y;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 y;\n"
            "    s32* ptr;\n"
            "    a = *ptr;\n"
            "    b = y;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 y;\n"
            "    Obj obj;\n"
            "    a = obj.field;\n"
            "    b = y;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 y;\n"
            "    s32 arr[2];\n"
            "    a = arr[0];\n"
            "    b = y;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    s32 y;\n"
            "    a = later;\n"
            "    b = y;\n"
            "    s32 later;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    volatile s32 a;\n"
            "    s32 b;\n"
            "    s32 x;\n"
            "    s32 y;\n"
            "    a = x;\n"
            "    b = y;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    a = 1;\n"
            "    s32 c;\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    a = 1;\n"
            "    sink(b);\n"
            "}\n"
        ),
        (
            "s32 global_value;\n"
            "void target(void) {\n"
            "    s32 a;\n"
            "    global_value = 1;\n"
            "    a = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    Obj* obj;\n"
            "    obj->field = 1;\n"
            "    a = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 arr[2];\n"
            "    arr[0] = 1;\n"
            "    a = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32* ptr;\n"
            "    *ptr = 1;\n"
            "    a = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    a = 1;\n"
            "    return;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "label:\n"
            "    a = 1;\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(s32 kind) {\n"
            "    switch (kind) {\n"
            "    case 1: {\n"
            "        s32 a;\n"
            "        s32 b;\n"
            "        a = 1;\n"
            "        b = 2;\n"
            "        break;\n"
            "    }\n"
            "    }\n"
            "}\n"
        ),
        (
            "void target(s32 kind) {\n"
            "    switch (kind) {\n"
            "    default: {\n"
            "        s32 a;\n"
            "        s32 b;\n"
            "        a = 1;\n"
            "        b = 2;\n"
            "        break;\n"
            "    }\n"
            "    }\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    a = 1; // preserve order\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    /* preserve order */\n"
            "    a = 1;\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "#if ENABLE_ORDER\n"
            "    a = 1;\n"
            "#endif\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    if (flag) {\n"
            "        a = 1;\n"
            "    }\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    if (flag)\n"
            "        a = 1;\n"
            "    b = 2;\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    s32 a;\n"
            "    s32 b;\n"
            "    a = 1;\n"
            "    b = 2;\n"
            "    /* preserve order */\n"
            "}\n"
        ),
        (
            "void target(void) {\n"
            "    if (flag) {\n"
            "        s32 a;\n"
            "        s32 b;\n"
            "    }\n"
            "    if (other) {\n"
            "        a = 1;\n"
            "        b = 2;\n"
            "    }\n"
            "}\n"
        ),
    ),
)
def test_independent_statement_order_rejects_unsafe_shapes(source: str) -> None:
    assert not _statement_order_probes(source, max_per_family=3)


def test_switch_case_order_rejects_pointer_declarations() -> None:
    source = (
        "void target(void) {\n"
        "    switch (kind) {\n"
        "    case 7:\n"
        "        State* p;\n"
        "        break;\n"
        "    case 9:\n"
        "        c();\n"
        "        break;\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    assert "switch_case_order_default_shape" not in {probe.family_id for probe in probes}
