"""Tests for the helper_extract transform family (transform_corpus.helper_extract)."""
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


def _helper_shape_probes(source: str, *, max_per_family: int = 3):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("helper_shape",),
        max_per_family=max_per_family,
    )


def test_generate_transform_probes_inlines_simple_static_helper_call() -> None:
    source = (
        "typedef int s32;\n"
        "static s32 add_bonus(s32 base, s32 inc) {\n"
        "    return base + inc;\n"
        "}\n"
        "\n"
        "void target(s32 arg0, s32 arg1) {\n"
        "    s32 score;\n"
        "    score = add_bonus(arg0, arg1);\n"
        "}\n"
    )

    probes = _helper_shape_probes(source)

    inline_probes = [
        probe
        for probe in probes
        if probe.mutator_key == "inline_simple_helper_call"
    ]
    assert inline_probes
    inline = inline_probes[0]
    assert "    score = (arg0 + arg1);" in inline.candidate_text
    assert inline.family_id == "helper_shape"
    assert inline.probe_id == "helper_shape@0"
    assert inline.span[0] < inline.span[1]
    assert transform_probe_key(inline) == "transform-corpus:helper_shape:0"
    assert inline.payload["helper_name"] == "add_bonus"
    assert inline.payload["return_expr"] == "base + inc"
    assert inline.payload["parameter_map"] == (("base", "arg0"), ("inc", "arg1"))
    assert isinstance(inline.payload["helper_span"], tuple)


def test_generate_transform_probes_inlines_assign_then_return_helper() -> None:
    source = (
        "typedef int s32;\n"
        "static s32 add_bonus(s32 base, s32 inc) {\n"
        "    s32 result;\n"
        "    result = base + inc;\n"
        "    return result;\n"
        "}\n"
        "\n"
        "void target(s32 arg0, s32 arg1) {\n"
        "    s32 score;\n"
        "    score = add_bonus(arg0, arg1);\n"
        "}\n"
    )

    probes = _helper_shape_probes(source)

    inline_probes = [
        probe
        for probe in probes
        if probe.mutator_key == "inline_simple_helper_call"
    ]
    assert inline_probes
    inline = inline_probes[0]
    assert "    score = (arg0 + arg1);" in inline.candidate_text
    assert inline.payload["return_expr"] == "base + inc"


def test_generate_transform_probes_extracts_repeated_assignment_helper() -> None:
    source = (
        "typedef int s32;\n"
        "void target(s32 arg0, s32 arg1) {\n"
        "    s32 left;\n"
        "    s32 right;\n"
        "    left = arg0 + arg1;\n"
        "    right = arg0 + arg1;\n"
        "}\n"
    )

    probes = _helper_shape_probes(source)

    extraction_probes = [
        probe
        for probe in probes
        if probe.mutator_key == "extract_repeated_assignment_helper"
    ]
    assert extraction_probes
    extracted = extraction_probes[0]
    assert (
        "static s32 target__helper_shape_0(s32 arg0, s32 arg1)"
        in extracted.candidate_text
    )
    assert (
        extracted.candidate_text.index(
            "static s32 target__helper_shape_0(s32 arg0, s32 arg1)"
        )
        < extracted.candidate_text.index("void target(s32 arg0, s32 arg1)")
    )
    assert "    left = target__helper_shape_0(arg0, arg1);" in extracted.candidate_text
    assert "    right = target__helper_shape_0(arg0, arg1);" in extracted.candidate_text
    assert extracted.family_id == "helper_shape"
    assert extracted.probe_id.startswith("helper_shape@")
    assert extracted.span[0] < extracted.span[1]
    assert transform_probe_key(extracted).startswith("transform-corpus:helper_shape:")
    assert extracted.payload["helper_name"] == "target__helper_shape_0"
    assert extracted.payload["target_function"] == "target"
    assert extracted.payload["rhs"] == "arg0 + arg1"
    assert extracted.payload["operand_order"] == ("arg0", "arg1")
    assert extracted.payload["operand_types"] == (("arg0", "s32"), ("arg1", "s32"))
    assert len(extracted.payload["line_replacements"]) == 2


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "free helper identifier captured by target-local same name",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 base) {\n"
                "    return base + bonus;\n"
                "}\n"
                "void target(s32 arg0) {\n"
                "    s32 bonus;\n"
                "    score = add_bonus(arg0);\n"
                "}\n"
            ),
        ),
        (
            "pointer and member access",
            (
                "typedef int s32;\n"
                "typedef struct Obj Obj;\n"
                "static s32 load_bonus(Obj* obj) {\n"
                "    return obj->bonus;\n"
                "}\n"
                "void target(Obj* obj) {\n"
                "    score = load_bonus(obj);\n"
                "}\n"
            ),
        ),
        (
            "direct call in helper body",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 base) {\n"
                "    return get_bonus(base);\n"
                "}\n"
                "void target(s32 arg0) {\n"
                "    score = add_bonus(arg0);\n"
                "}\n"
            ),
        ),
        (
            "indirect call in helper body",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 (*fn)(s32), s32 base) {\n"
                "    return fn(base);\n"
                "}\n"
                "void target(s32 (*fn)(s32), s32 arg0) {\n"
                "    score = add_bonus(fn, arg0);\n"
                "}\n"
            ),
        ),
        (
            "preprocessor region",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 base) {\n"
                "#if 1\n"
                "    return base;\n"
                "#endif\n"
                "}\n"
                "void target(s32 arg0) {\n"
                "    score = add_bonus(arg0);\n"
                "}\n"
            ),
        ),
        (
            "label case and default",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 base) {\n"
                "again:\n"
                "    switch (base) {\n"
                "    case 0:\n"
                "        return 1;\n"
                "    default:\n"
                "        return base;\n"
                "    }\n"
                "}\n"
                "void target(s32 arg0) {\n"
                "    score = add_bonus(arg0);\n"
                "}\n"
            ),
        ),
        (
            "multiple returns",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 base) {\n"
                "    if (base != 0) {\n"
                "        return base;\n"
                "    }\n"
                "    return 1;\n"
                "}\n"
                "void target(s32 arg0) {\n"
                "    score = add_bonus(arg0);\n"
                "}\n"
            ),
        ),
        (
            "side-effecting call argument",
            (
                "typedef int s32;\n"
                "static s32 add_bonus(s32 base, s32 inc) {\n"
                "    return base + inc;\n"
                "}\n"
                "void target(s32 arg1) {\n"
                "    score = add_bonus(next(), arg1);\n"
                "}\n"
            ),
        ),
        (
            "helper return conversion",
            (
                "typedef signed char s8;\n"
                "typedef int s32;\n"
                "static s8 narrow(s32 base) {\n"
                "    return base;\n"
                "}\n"
                "void target(s32 arg0) {\n"
                "    score = narrow(arg0);\n"
                "}\n"
            ),
        ),
        (
            "unknown extraction operand type",
            (
                "typedef int s32;\n"
                "void target(s32 arg0) {\n"
                "    s32 left;\n"
                "    s32 right;\n"
                "    left = arg0 + local;\n"
                "    right = arg0 + local;\n"
                "}\n"
            ),
        ),
        (
            "mixed destination types",
            (
                "typedef int s32;\n"
                "typedef float f32;\n"
                "void target(s32 arg0, s32 arg1) {\n"
                "    s32 left;\n"
                "    f32 right;\n"
                "    left = arg0 + arg1;\n"
                "    right = arg0 + arg1;\n"
                "}\n"
            ),
        ),
        (
            "calls in extraction rhs",
            (
                "typedef int s32;\n"
                "void target(s32 arg0) {\n"
                "    s32 left;\n"
                "    s32 right;\n"
                "    left = get_value(arg0);\n"
                "    right = get_value(arg0);\n"
                "}\n"
            ),
        ),
        (
            "array indexing in extraction rhs",
            (
                "typedef int s32;\n"
                "void target(s32* values, s32 idx) {\n"
                "    s32 left;\n"
                "    s32 right;\n"
                "    left = values[idx];\n"
                "    right = values[idx];\n"
                "}\n"
            ),
        ),
        (
            "singleton expression",
            (
                "typedef int s32;\n"
                "void target(s32 arg0, s32 arg1) {\n"
                "    s32 left;\n"
                "    left = arg0 + arg1;\n"
                "}\n"
            ),
        ),
    ),
)
def test_helper_shape_rejects_unsafe_fixtures(case: str, source: str) -> None:
    probes = _helper_shape_probes(source)

    assert "helper_shape" not in {probe.family_id for probe in probes}, case


@pytest.mark.parametrize(
    ("case", "body"),
    (
        (
            "preprocessor call site",
            (
                "void target(s32 arg0) {\n"
                "#if 1\n"
                "    score = add_bonus(arg0);\n"
                "#endif\n"
                "}\n"
            ),
        ),
        (
            "label call site",
            (
                "void target(s32 arg0) {\n"
                "again:\n"
                "    score = add_bonus(arg0);\n"
                "}\n"
            ),
        ),
        (
            "case call site",
            (
                "void target(s32 arg0) {\n"
                "    switch (arg0) {\n"
                "    case 0:\n"
                "        score = add_bonus(arg0);\n"
                "        break;\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "block-comment call site",
            (
                "void target(s32 arg0) {\n"
                "    /*\n"
                "    score = add_bonus(arg0);\n"
                "    */\n"
                "}\n"
            ),
        ),
    ),
)
def test_helper_shape_rejects_unsafe_inline_target_regions(case: str, body: str) -> None:
    source = (
        "typedef int s32;\n"
        "static s32 add_bonus(s32 base) {\n"
        "    return base;\n"
        "}\n"
        f"{body}"
    )

    probes = _helper_shape_probes(source)

    assert "helper_shape" not in {probe.family_id for probe in probes}, case
