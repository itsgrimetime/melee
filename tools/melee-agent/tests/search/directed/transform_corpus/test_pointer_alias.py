"""Tests for the pointer_alias transform family (transform_corpus.pointer_alias)."""
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


def test_global_pointer_alias_probe_only_rewrites_target_function() -> None:
    source = (
        "typedef struct State { int field; int other; } State;\n"
        "State lbl_80472D28;\n"
        "void helper(void) {\n"
        "    lbl_80472D28.field = 1;\n"
        "    use(lbl_80472D28.other);\n"
        "}\n"
        "void target(void) {\n"
        "    lbl_80472D28.field = 2;\n"
        "    use(lbl_80472D28.other);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    alias = next(
        probe for probe in probes if probe.family_id == "global_pointer_alias_shape"
    )
    assert "void helper(void) {\n    lbl_80472D28.field = 1;" in alias.candidate_text
    assert "State* lbl_80472D28_alias = &lbl_80472D28;" in alias.candidate_text
    assert "lbl_80472D28_alias->field = 2;" in alias.candidate_text


def test_global_pointer_alias_probe_covers_mndiagram_inputproc_transfer() -> None:
    source = (
        "typedef struct MenuFlow { int hovered_selection; int buttons; } MenuFlow;\n"
        "MenuFlow mn_804A04F0;\n"
        "void mnDiagram_InputProc(void) {\n"
        "    if (mn_804A04F0.hovered_selection != 0) {\n"
        "        use(mn_804A04F0.hovered_selection);\n"
        "    }\n"
        "    mn_804A04F0.buttons = read_buttons();\n"
        "    use(mn_804A04F0.hovered_selection);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_InputProc",
        unit="melee/mn/mndiagram",
        force_phys={24: 27},
        families=("global_pointer_alias_shape",),
        max_per_family=1,
    )

    alias = next(
        probe for probe in probes if probe.family_id == "global_pointer_alias_shape"
    )
    assert "MenuFlow* mn_804A04F0_alias = &mn_804A04F0;" in alias.candidate_text
    assert "if (mn_804A04F0_alias->hovered_selection != 0)" in alias.candidate_text
    assert "mn_804A04F0_alias->buttons = read_buttons();" in alias.candidate_text


def test_global_pointer_alias_does_not_rewrite_string_literals() -> None:
    source = (
        "typedef struct State { int field; int other; } State;\n"
        "State lbl_80472D28;\n"
        "void target(void) {\n"
        "    lbl_80472D28.field = 2;\n"
        "    puts(\"lbl_80472D28.other\");\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    assert "global_pointer_alias_shape" not in {probe.family_id for probe in probes}
