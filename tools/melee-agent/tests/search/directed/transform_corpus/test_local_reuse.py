"""Tests for the local_reuse transform family (transform_corpus.local_reuse)."""
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


def _same_type_reuse_probes(source: str, *, max_per_family: int = 3):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("same_type_local_lifetime_reuse",),
        max_per_family=max_per_family,
    )


def test_generate_transform_probes_materializes_same_type_pointer_lifetime_reuse() -> None:
    source = (
        "typedef struct ItemLink ItemLink;\n"
        "struct ItemLink { ItemLink* next; int pos; };\n"
        "static ItemLink* it_802BCB88_prev(ItemLink* link) {\n"
        "    return link->next;\n"
        "}\n"
        "\n"
        "void target(ItemLink* link) {\n"
        "    ItemLink* cur;\n"
        "    ItemLink* prev;\n"
        "    int pos0;\n"
        "    int pos1;\n"
        "\n"
        "    cur = link->next;\n"
        "    if (cur != NULL) {\n"
        "        pos0 = cur->pos;\n"
        "    }\n"
        "    cur = cur->next;\n"
        "\n"
        "    prev = it_802BCB88_prev(link);\n"
        "    if (prev != NULL) {\n"
        "        pos1 = prev->pos;\n"
        "    }\n"
        "    use(pos0, pos1);\n"
        "}\n"
    )

    probes = _same_type_reuse_probes(source, max_per_family=1)

    reuse = next(
        probe for probe in probes if probe.family_id == "same_type_local_lifetime_reuse"
    )
    assert reuse.mutator_key == "reuse_same_type_local_lifetime"
    assert reuse.probe_id == "same_type_local_lifetime_reuse@0"
    assert transform_probe_key(reuse) == "transform-corpus:same_type_local_lifetime_reuse:0"
    assert "static ItemLink* it_802BCB88_prev(ItemLink* link)" in reuse.candidate_text
    assert "    ItemLink* cur;\n" in reuse.candidate_text
    assert "    ItemLink* prev;\n" not in reuse.candidate_text
    assert "    cur = it_802BCB88_prev(link);\n" in reuse.candidate_text
    assert "    if (cur != NULL) {\n        pos1 = cur->pos;\n" in reuse.candidate_text
    assert reuse.payload["reused_name"] == "cur"
    assert reuse.payload["original_name"] == "prev"
    assert reuse.payload["local_type"] == "ItemLink*"
    assert reuse.payload["replacement_count"] == 3
    assert len(reuse.payload["replacement_spans"]) == 3
    assert isinstance(reuse.payload["reused_decl_span"], tuple)
    assert isinstance(reuse.payload["original_decl_span"], tuple)
    assert reuse.span[0] < reuse.span[1]


def test_same_type_local_lifetime_reuse_supports_simple_scalar_locals() -> None:
    source = (
        "void target(int a, int b) {\n"
        "    int tmp;\n"
        "    int result;\n"
        "    tmp = a + 1;\n"
        "    sink(tmp);\n"
        "    result = b + 2;\n"
        "    sink(result);\n"
        "}\n"
    )

    probes = _same_type_reuse_probes(source, max_per_family=1)

    reuse = next(
        probe for probe in probes if probe.family_id == "same_type_local_lifetime_reuse"
    )
    assert "    int result;\n" not in reuse.candidate_text
    assert "    tmp = b + 2;\n" in reuse.candidate_text
    assert reuse.candidate_text.count("sink(tmp);") == 2
    assert reuse.payload["reused_name"] == "tmp"
    assert reuse.payload["original_name"] == "result"
    assert reuse.payload["local_type"] == "int"


def test_same_type_local_lifetime_reuse_preserves_comments_literals_and_members() -> None:
    source = (
        "typedef struct State { int prev; int value; } State;\n"
        "void target(State* state, int a, int b) {\n"
        "    int cur;\n"
        "    int prev;\n"
        "    cur = a;\n"
        "    sink(cur);\n"
        "    OSReport(\"prev still means field name\");\n"
        "    /* prev in a comment and { braces } must stay text */\n"
        "    sink(state->prev);\n"
        "    prev = b;\n"
        "    sink(prev);\n"
        "}\n"
    )

    probes = _same_type_reuse_probes(source, max_per_family=1)

    reuse = next(
        probe for probe in probes if probe.family_id == "same_type_local_lifetime_reuse"
    )
    assert "    int prev;\n" not in reuse.candidate_text
    assert "    cur = b;\n" in reuse.candidate_text
    assert "OSReport(\"prev still means field name\");" in reuse.candidate_text
    assert "/* prev in a comment and { braces } must stay text */" in reuse.candidate_text
    assert "sink(state->prev);" in reuse.candidate_text
    assert "sink(state->cur);" not in reuse.candidate_text


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "overlapping survivor use after later first use",
            (
                "typedef struct ItemLink ItemLink;\n"
                "void target(ItemLink* link) {\n"
                "    ItemLink* cur;\n"
                "    ItemLink* prev;\n"
                "    cur = link->next;\n"
                "    prev = link;\n"
                "    sink(cur);\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "later first event is read",
            (
                "typedef struct ItemLink ItemLink;\n"
                "void target(ItemLink* link) {\n"
                "    ItemLink* cur;\n"
                "    ItemLink* prev;\n"
                "    cur = link->next;\n"
                "    sink(cur);\n"
                "    sink(prev);\n"
                "    prev = link;\n"
                "}\n"
            ),
        ),
        (
            "address taken survivor with whitespace",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(& cur);\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "address taken later local with whitespace",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(& prev);\n"
                "}\n"
            ),
        ),
        (
            "parenthesized address taken later local",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(&((prev)));\n"
                "}\n"
            ),
        ),
        (
            "later declaration inside nested scope",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    if (a != 0) {\n"
                "        int prev;\n"
                "        prev = b;\n"
                "        sink(prev);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "nested declaration shadows survivor",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    if (prev != 0) {\n"
                "        int cur;\n"
                "        cur = prev;\n"
                "        sink(cur);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "nested declaration shadows later local with initializer",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    if (prev != 0) {\n"
                "        int prev = 0;\n"
                "        sink(prev);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "nested declaration shadows later local with comment",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    if (prev != 0) {\n"
                "        int prev; // shadow\n"
                "        prev = b + 1;\n"
                "        sink(prev);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "preprocessor region",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "#if 1\n"
                "    sink(cur);\n"
                "#endif\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "label sensitive body",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "again:\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "case sensitive body",
            (
                "void target(int a, int b) {\n"
                "    switch (a) {\n"
                "    case 0:\n"
                "        break;\n"
                "    }\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "loop cross iteration lifetime",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    while (b != 0) {\n"
                "        sink(cur);\n"
                "        prev = b;\n"
                "        sink(prev);\n"
                "        b--;\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "different types",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    float prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "later declaration initializer",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev = 0;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "candidate declaration trailing comment",
            (
                "void target(int a, int b) {\n"
                "    int cur;\n"
                "    int prev; // later phase\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    prev = b;\n"
                "    sink(prev);\n"
                "}\n"
            ),
        ),
        (
            "name appears only in comments and literals",
            (
                "void target(int a) {\n"
                "    int cur;\n"
                "    int prev;\n"
                "    cur = a;\n"
                "    sink(cur);\n"
                "    OSReport(\"prev\");\n"
                "    /* prev */\n"
                "}\n"
            ),
        ),
    ),
)
def test_same_type_local_lifetime_reuse_rejects_unsafe_shapes(
    case: str, source: str
) -> None:
    probes = _same_type_reuse_probes(source, max_per_family=3)

    assert "same_type_local_lifetime_reuse" not in {probe.family_id for probe in probes}, case
