"""Tests for the return_tail_call transform family (transform_corpus.return_tail_call)."""
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


def test_return_tail_call_probe_rewrites_target_line_when_call_repeats() -> None:
    source = (
        "typedef int s32;\n"
        "typedef struct Item Item;\n"
        "s32 fn_8017F0A0(Item* it);\n"
        "static void helper(Item* it) {\n"
        "    fn_8017F0A0(it);\n"
        "}\n"
        "static void target(Item* it) {\n"
        "    fn_8017F0A0(it);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    ret = next(probe for probe in probes if probe.family_id == "void_to_value_return_shape")
    assert "static void helper(Item* it) {\n    fn_8017F0A0(it);" in ret.candidate_text
    assert "static s32 target(Item* it)" in ret.candidate_text
    assert "static s32 target(Item* it) {\n    return fn_8017F0A0(it);" in ret.candidate_text


def test_return_tail_call_probe_rejects_nested_branch_tail() -> None:
    source = (
        "typedef int s32;\n"
        "typedef struct Item Item;\n"
        "s32 fn_8017F0A0(Item* it);\n"
        "static void target(Item* it) {\n"
        "    if (it != NULL) {\n"
        "        fn_8017F0A0(it);\n"
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

    assert "void_to_value_return_shape" not in {probe.family_id for probe in probes}
