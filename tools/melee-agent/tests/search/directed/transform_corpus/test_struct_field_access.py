"""Tests for the struct_field_access transform family (transform_corpus.struct_field_access)."""
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


def _raw_index_struct_field_probes(source: str, *, max_per_family: int = 4):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("raw_index_struct_field_shape",),
        max_per_family=max_per_family,
    )


def _data_table_indirection_probes(source: str, *, max_per_family: int = 3):
    return generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        families=("data_table_indirection_shape",),
        max_per_family=max_per_family,
    )


def test_raw_index_struct_field_rewrites_source_local_struct_fields() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef int s32;\n"
        "typedef struct Entry {\n"
        "    u8 pad0[0x10];\n"
        "    s32 voice_id;\n"
        "    s32 entity;\n"
        "} Entry;\n"
        "\n"
        "void target(Entry* entries, s32 i, s32 value) {\n"
        "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
        "    *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x14) = value;\n"
        "}\n"
    )

    probes = [
        probe
        for probe in _raw_index_struct_field_probes(source, max_per_family=4)
        if probe.family_id == "raw_index_struct_field_shape"
    ]

    assert len(probes) == 2
    assert {probe.mutator_key for probe in probes} == {
        "rewrite_raw_index_struct_field"
    }
    by_access = {probe.payload["access_kind"]: probe for probe in probes}
    assert set(by_access) == {"load", "store"}

    load = by_access["load"]
    assert "value = entries[i].voice_id;" in load.candidate_text
    assert load.payload["span_text"] == (
        "*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10)"
    )
    assert load.payload["replacement_text"] == "entries[i].voice_id"
    assert load.payload["field_offset"] == 0x10
    assert load.payload["field_type"] == "s32"
    assert load.payload["field_name"] == "voice_id"
    assert load.payload["struct_type"] == "Entry"
    assert load.payload["base"] == "entries"
    assert load.payload["index_expr"] == "i"
    assert load.payload["proof_source"] == "source-local-struct-layout"

    store = by_access["store"]
    assert "entries[i].entity = value;" in store.candidate_text
    assert store.payload["span_text"] == (
        "*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x14)"
    )
    assert store.payload["replacement_text"] == "entries[i].entity"
    assert store.payload["field_offset"] == 0x14
    assert store.payload["field_type"] == "s32"
    assert store.payload["field_name"] == "entity"
    assert store.payload["struct_type"] == "Entry"
    assert store.payload["base"] == "entries"
    assert store.payload["index_expr"] == "i"
    assert store.payload["proof_source"] == "source-local-struct-layout"


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "struct typedef after target",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
                "}\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
            ),
        ),
        (
            "implicit alignment gap",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    u8 pad[1];\n"
                "    s32 field;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x4);\n"
                "}\n"
            ),
        ),
        (
            "mismatched cast type",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef short s16;\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s16*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
                "}\n"
            ),
        ),
        (
            "index scale mismatch",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * 8 + 0x10);\n"
                "}\n"
            ),
        ),
        (
            "tail padding numeric scale mismatch",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    s32 word;\n"
                "    u8 tail;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * 5 + 0x0);\n"
                "}\n"
            ),
        ),
        (
            "non-pointer base parameter",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
                "void target(Entry entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
                "}\n"
            ),
        ),
        (
            "complex index expression",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + (i + 1) * sizeof(Entry) + 0x10);\n"
                "}\n"
            ),
        ),
        (
            "preprocessor-hidden struct declaration",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "#if 0\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
                "#endif\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
                "}\n"
            ),
        ),
        (
            "bitfield member",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id:1;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
                "}\n"
            ),
        ),
        (
            "duplicate field proof at same offset and type",
            (
                "typedef unsigned char u8;\n"
                "typedef int s32;\n"
                "typedef struct Entry {\n"
                "    u8 pad0[0x10];\n"
                "    s32 voice_id;\n"
                "} Entry;\n"
                "typedef struct EntryAlias {\n"
                "    u8 pad0[0x10];\n"
                "    s32 alias;\n"
                "} Entry;\n"
                "void target(Entry* entries, s32 i, s32 value) {\n"
                "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
                "}\n"
            ),
        ),
    ),
)
def test_raw_index_struct_field_rejects_unsafe_shapes(
    case: str, source: str
) -> None:
    probes = _raw_index_struct_field_probes(source, max_per_family=4)

    assert "raw_index_struct_field_shape" not in {
        probe.family_id for probe in probes
    }, case


def test_data_table_indirection_rewrites_source_local_immutable_table() -> None:
    source = (
        "typedef int s32;\n"
        "extern s32 table_a[];\n"
        "extern s32 table_b[];\n"
        "extern s32 table_c[];\n"
        "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
        "\n"
        "void target(s32 idx, s32 value) {\n"
        "    value = table_b[idx];\n"
        "}\n"
    )

    probes = [
        probe
        for probe in _data_table_indirection_probes(source, max_per_family=3)
        if probe.family_id == "data_table_indirection_shape"
    ]

    assert len(probes) == 1
    probe = probes[0]
    assert probe.family_id == "data_table_indirection_shape"
    assert probe.mutator_key == "rewrite_data_table_indirection"
    assert "value = sOuterTable[1][idx];" in probe.candidate_text
    assert probe.payload["span_text"] == "table_b[idx]"
    assert probe.payload["replacement_text"] == "sOuterTable[1][idx]"
    assert probe.payload["table_symbol"] == "sOuterTable"
    assert probe.payload["element_symbol"] == "table_b"
    assert probe.payload["table_index"] == 1
    assert probe.payload["index_expr"] == "idx"
    assert probe.payload["element_type"] == "s32"
    assert probe.payload["proof_source"] == "source-local-immutable-table"
    assert "declaration_span" in probe.payload


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "mutable table declaration",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "duplicate element initializer",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_b };\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "missing top-level direct-symbol declaration",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "struct member is not a top-level direct-symbol declaration",
            (
                "typedef int s32;\n"
                "typedef struct Holder {\n"
                "    s32 table_b[4];\n"
                "} Holder;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "table declaration after target",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
            ),
        ),
        (
            "element write",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    table_b[idx] = value;\n"
                "}\n"
            ),
        ),
        (
            "compound element write",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    table_b[idx] += value;\n"
                "}\n"
            ),
        ),
        (
            "address-take element symbol",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    use(&table_b);\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "element reassignment",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "extern s32 other[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    table_b = other;\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "outer table write",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    sOuterTable[1] = table_c;\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "complex index expression",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx + 1];\n"
                "}\n"
            ),
        ),
        (
            "local element shadow",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    s32* table_b;\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "local outer table shadow",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "void target(s32 idx, s32 value) {\n"
                "    s32** sOuterTable;\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "local table declaration inside helper",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "void helper(void) {\n"
                "    static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "}\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
        (
            "preprocessor-hidden table declaration",
            (
                "typedef int s32;\n"
                "extern s32 table_a[];\n"
                "extern s32 table_b[];\n"
                "extern s32 table_c[];\n"
                "#if 0\n"
                "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
                "#endif\n"
                "void target(s32 idx, s32 value) {\n"
                "    value = table_b[idx];\n"
                "}\n"
            ),
        ),
    ),
)
def test_data_table_indirection_rejects_unsafe_shapes(
    case: str, source: str
) -> None:
    probes = _data_table_indirection_probes(source, max_per_family=3)

    assert "data_table_indirection_shape" not in {
        probe.family_id for probe in probes
    }, case


def test_raw_pointer_offset_rejects_implicit_alignment_layout() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef int s32;\n"
        "typedef struct Bad { u8 pad[1]; s32 field; } Bad;\n"
        "void target(Bad* bad) {\n"
        "    *(s32*) ((u8*) bad + 1) = value;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    assert "raw_pointer_offset_struct_field_shape" not in {probe.family_id for probe in probes}
