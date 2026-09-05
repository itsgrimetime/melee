"""Tests for the float_literal transform family (transform_corpus.float_literal)."""
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


def test_global_float_literal_replaces_f32_literal_with_unique_constant() -> None:
    source = (
        "typedef float f32;\n"
        "static const f32 lbl_804D8000 = 0.5f;\n"
        "void target(void) {\n"
        "    set_scale(0.5f);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    probe = next(
        probe for probe in probes
        if probe.family_id == "global_float_literal_shape"
        and probe.mutator_key == "replace_float_literal_with_global_constant"
    )
    assert "set_scale(lbl_804D8000);" in probe.candidate_text
    assert probe.payload["symbol"] == "lbl_804D8000"
    assert probe.payload["literal"] == "0.5f"
    assert probe.payload["width"] == "f32"
    assert probe.payload["target_function"] == "target"


def test_global_float_literal_replaces_f64_literal_with_unique_constant() -> None:
    source = (
        "typedef double f64;\n"
        "const f64 lbl_804D8008 = 0.75;\n"
        "void target(void) {\n"
        "    set_weight(0.75);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    probe = next(
        probe for probe in probes
        if probe.family_id == "global_float_literal_shape"
        and probe.mutator_key == "replace_float_literal_with_global_constant"
    )
    assert "set_weight(lbl_804D8008);" in probe.candidate_text
    assert probe.payload["symbol"] == "lbl_804D8008"
    assert probe.payload["literal"] == "0.75"
    assert probe.payload["width"] == "f64"


def test_global_float_literal_replaces_constant_reference_with_literal() -> None:
    source = (
        "typedef float f32;\n"
        "static const f32 lbl_804D8000 = 0.5f;\n"
        "void target(void) {\n"
        "    set_scale(lbl_804D8000);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("global_float_literal_shape",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes
        if probe.mutator_key == "replace_global_float_constant_with_literal"
    )
    assert "set_scale(0.5f);" in probe.candidate_text
    assert probe.payload["symbol"] == "lbl_804D8000"
    assert probe.payload["literal"] == "0.5f"
    assert probe.payload["mode"] == "symbol_to_literal"


def test_global_float_literal_replaces_returned_constant_reference() -> None:
    source = (
        "typedef float f32;\n"
        "static const f32 lbl_804D8000 = 0.5f;\n"
        "f32 target(void) {\n"
        "    return lbl_804D8000;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("global_float_literal_shape",),
        max_per_family=2,
    )

    probe = next(
        probe for probe in probes
        if probe.mutator_key == "replace_global_float_constant_with_literal"
    )
    assert "return 0.5f;" in probe.candidate_text


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "duplicate rounded f32 value",
            (
                "typedef float f32;\n"
                "static const f32 lbl_a = 0.1f;\n"
                "static const f32 lbl_b = 0.10000000149011612f;\n"
                "void target(void) {\n"
                "    use(0.1f);\n"
                "}\n"
            ),
        ),
        (
            "f32 edge decimal must not double round",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = "
                "1.000000059604644775390625000000000000000000001f;\n"
                "void target(void) {\n"
                "    use(1.0f);\n"
                "}\n"
            ),
        ),
        (
            "negative zero literal must not bind positive zero constant",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.0f;\n"
                "void target(void) {\n"
                "    use(-0.0f);\n"
                "}\n"
            ),
        ),
        (
            "f32 declaration missing suffix",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5;\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "f64 declaration has f suffix",
            (
                "typedef double f64;\n"
                "static const f64 lbl_804D8008 = 0.75f;\n"
                "void target(void) {\n"
                "    use(0.75);\n"
                "}\n"
            ),
        ),
        (
            "local constant",
            (
                "typedef float f32;\n"
                "void helper(void) {\n"
                "    static const f32 lbl_804D8000 = 0.5f;\n"
                "}\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "volatile global",
            (
                "typedef float f32;\n"
                "volatile const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "hex float",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0x1p-1f;\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "macro expression",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = M_PI;\n"
                "void target(void) {\n"
                "    use(3.14159f);\n"
                "}\n"
            ),
        ),
        (
            "commented declaration",
            (
                "typedef float f32;\n"
                "/* static const f32 lbl_804D8000 = 0.5f; */\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "disabled declaration",
            (
                "typedef float f32;\n"
                "#if 0\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "#endif\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "else-disabled declaration",
            (
                "typedef float f32;\n"
                "#if 1\n"
                "extern int alive;\n"
                "#else\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "#endif\n"
                "void target(void) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "disabled body literal",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "#if 0\n"
                "    use(0.5f);\n"
                "#endif\n"
                "}\n"
            ),
        ),
        (
            "string literal body",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    OSReport(\"0.5f\");\n"
                "}\n"
            ),
        ),
        (
            "parameter shadow",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(f32 lbl_804D8000) {\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "top level local shadow",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    f32 lbl_804D8000;\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "multi declarator local shadow",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    f32 other, lbl_804D8000;\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "pointer local shadow",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    f32* lbl_804D8000;\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "function pointer local shadow",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    f32 (*lbl_804D8000)(void);\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "nested local shadow",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    if (flag) {\n"
                "        f32 lbl_804D8000;\n"
                "    }\n"
                "    use(0.5f);\n"
                "}\n"
            ),
        ),
        (
            "static local initializer",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    static f32 local = 0.5f;\n"
                "}\n"
            ),
        ),
        (
            "address taken symbol",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    use(&lbl_804D8000);\n"
                "}\n"
            ),
        ),
        (
            "parenthesized address taken symbol",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    use(&(lbl_804D8000));\n"
                "}\n"
            ),
        ),
        (
            "commented address taken symbol",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    use(& /* c */ lbl_804D8000);\n"
                "}\n"
            ),
        ),
        (
            "commented parenthesized address taken symbol",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    use(& /* c */ (lbl_804D8000));\n"
                "}\n"
            ),
        ),
        (
            "multiline static local literal initializer",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    static f32 local =\n"
                "        0.5f;\n"
                "}\n"
            ),
        ),
        (
            "static local symbol initializer",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    static f32 local = lbl_804D8000;\n"
                "}\n"
            ),
        ),
        (
            "multiline static local symbol initializer",
            (
                "typedef float f32;\n"
                "static const f32 lbl_804D8000 = 0.5f;\n"
                "void target(void) {\n"
                "    static f32 local =\n"
                "        lbl_804D8000;\n"
                "}\n"
            ),
        ),
    ),
)
def test_global_float_literal_rejects_unsafe_cases(case: str, source: str) -> None:
    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("global_float_literal_shape",),
        max_per_family=2,
    )

    assert "global_float_literal_shape" not in {
        probe.family_id for probe in probes
    }, case
