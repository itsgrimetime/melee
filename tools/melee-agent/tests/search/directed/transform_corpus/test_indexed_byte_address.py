"""Tests for non-struct indexed byte-array address-temp steering probes."""
from __future__ import annotations

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import generate_transform_probes


def test_indexed_byte_address_temp_generates_same_line_variants() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "struct MnDiagramData { u8 sorted_names[25]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(int i, int j) {\n"
        "    u8 candidate;\n"
        "    u8 max_idx;\n"
        "    candidate = mnDiagram_804A076C.sorted_names[j + 1];\n"
        "    max_idx = mnDiagram_804A076C.sorted_names[j];\n"
        "    use(candidate, max_idx);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        families=("indexed_byte_address_temp_steering",),
        max_per_family=8,
    )

    indexed_probes = [
        probe
        for probe in probes
        if probe.family_id == "indexed_byte_address_temp_steering"
    ]
    assert indexed_probes
    candidate_probes = [
        probe
        for probe in indexed_probes
        if probe.payload["target_local"] == "candidate"
    ]
    by_strategy = {probe.payload["strategy"]: probe for probe in candidate_probes}
    assert "indexed-byte-parenthesize-index" in by_strategy
    assert "indexed-byte-value-temp" in by_strategy
    assert "indexed-byte-comma-normalize" in by_strategy

    parenthesized = by_strategy["indexed-byte-parenthesize-index"]
    assert parenthesized.mutator_key == "steer_indexed_byte_same_line_expr"
    assert (
        "candidate = mnDiagram_804A076C.sorted_names[(j + 1)];"
        in parenthesized.candidate_text
    )
    assert "candidate = &mnDiagram_804A076C.sorted_names" not in parenthesized.candidate_text

    value_temp = by_strategy["indexed-byte-value-temp"]
    assert value_temp.mutator_key == "steer_indexed_byte_value_temp"
    assert "    u8 candidate_probe;\n" in value_temp.candidate_text
    assert "    candidate_probe = mnDiagram_804A076C.sorted_names[j + 1];\n" in (
        value_temp.candidate_text
    )
    assert "    candidate = candidate_probe;" in value_temp.candidate_text

    comma = by_strategy["indexed-byte-comma-normalize"]
    assert "mnDiagram_804A076C.sorted_names[(0, j + 1)]" in comma.candidate_text


def test_indexed_byte_address_temp_generates_index_lifetime_temp() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "struct MnDiagramData { u8 sorted_names[25]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(int i, int j) {\n"
        "    u8 candidate;\n"
        "    u8 max_idx;\n"
        "    candidate = mnDiagram_804A076C.sorted_names[j + 1];\n"
        "    max_idx = mnDiagram_804A076C.sorted_names[j];\n"
        "    use(candidate, max_idx);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        families=("indexed_byte_address_temp_steering",),
        max_per_family=10,
    )

    index_temp = next(
        probe for probe in probes
        if probe.mutator_key == "steer_indexed_byte_index_temp"
        and probe.payload["target_local"] == "candidate"
    )
    assert index_temp.payload["strategy"] == "indexed-byte-index-temp"
    assert index_temp.payload["array_base"] == "mnDiagram_804A076C.sorted_names"
    assert index_temp.payload["index_expr"] == "j + 1"
    assert "    int sorted_names_idx_probe;\n" in index_temp.candidate_text
    assert "    sorted_names_idx_probe = j + 1;\n" in index_temp.candidate_text
    assert (
        "    candidate = mnDiagram_804A076C.sorted_names[sorted_names_idx_probe];"
        in index_temp.candidate_text
    )
    assert "mnDiagram_804A076C.sorted_names[j + 1]" not in index_temp.candidate_text


def test_indexed_byte_address_temp_generates_base_alias_probe() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "struct MnDiagramData { u8 sorted_names[25]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(int i, int j) {\n"
        "    u8 candidate;\n"
        "    u8 max_idx;\n"
        "    candidate = mnDiagram_804A076C.sorted_names[j + 1];\n"
        "    max_idx = mnDiagram_804A076C.sorted_names[j];\n"
        "    use(candidate, max_idx);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        families=("indexed_byte_address_temp_steering",),
        max_per_family=12,
    )

    base_alias = next(
        probe for probe in probes
        if probe.mutator_key == "steer_indexed_byte_base_alias"
        and probe.payload["target_local"] == "candidate"
    )
    assert base_alias.payload["strategy"] == "indexed-byte-base-alias"
    assert base_alias.payload["array_base"] == "mnDiagram_804A076C.sorted_names"
    assert base_alias.payload["index_expr"] == "j + 1"
    assert "    u8* sorted_names_base_probe;\n" in base_alias.candidate_text
    assert (
        "    sorted_names_base_probe = mnDiagram_804A076C.sorted_names;\n"
        in base_alias.candidate_text
    )
    assert "    candidate = sorted_names_base_probe[j + 1];" in base_alias.candidate_text
    assert "candidate = mnDiagram_804A076C.sorted_names[j + 1]" not in (
        base_alias.candidate_text
    )


def test_indexed_byte_base_alias_dispatch_applies_validated_span() -> None:
    source = (
        "void fn(void) {\n"
        "    u8 candidate;\n"
        "    candidate = data.sorted_names[j];\n"
        "}\n"
    )
    span_text = "    candidate = data.sorted_names[j];"
    replacement_text = (
        "    u8* sorted_names_base_probe;\n"
        "    sorted_names_base_probe = data.sorted_names;\n"
        "    candidate = sorted_names_base_probe[j];"
    )
    anchor = Anchor(
        mutator_key="steer_indexed_byte_base_alias",
        span=(source.index(span_text), source.index(span_text) + len(span_text)),
        payload={
            "span_text": span_text,
            "replacement_text": replacement_text,
        },
    )

    result = apply_mutator("steer_indexed_byte_base_alias", anchor, source)

    assert result is not None
    assert replacement_text in result


def test_indexed_byte_address_temp_handles_condition_expression_reads() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "struct MnDiagramData { u8 sorted_names[25]; };\n"
        "struct MnDiagramAssets { u8 sorted_names[25]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "char* GetNameText(int slot);\n"
        "void mnDiagram_SortNamesByKOs(int i) {\n"
        "    u32 totals[25];\n"
        "    int max_idx;\n"
        "    int j;\n"
        "    max_idx = i;\n"
        "    for (j = i + 1; j < 25; j++) {\n"
        "        if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != 0) &&\n"
        "            (totals[mnDiagram_804A076C.sorted_names[max_idx]] <\n"
        "             totals[mnDiagram_804A076C.sorted_names[j]])) {\n"
        "            max_idx = j;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        families=("indexed_byte_address_temp_steering",),
        max_per_family=8,
    )

    indexed_probes = [
        probe
        for probe in probes
        if probe.family_id == "indexed_byte_address_temp_steering"
    ]
    assert indexed_probes
    strategies = {probe.payload["strategy"] for probe in indexed_probes}
    assert "indexed-byte-parenthesize-index" in strategies
    assert "indexed-byte-comma-normalize" in strategies
    assert "indexed-byte-value-temp" in strategies
    assert "indexed-byte-index-temp" in strategies

    assert any(
        "GetNameText(mnDiagram_804A076C.sorted_names[(j)])" in probe.candidate_text
        for probe in indexed_probes
    )
    value_temp = next(
        probe
        for probe in indexed_probes
        if probe.payload["strategy"] == "indexed-byte-value-temp"
    )
    assert "    u8 sorted_names_probe;\n" in value_temp.candidate_text
    assert "        sorted_names_probe = mnDiagram_804A076C.sorted_names[j];\n" in (
        value_temp.candidate_text
    )
    assert "GetNameText(sorted_names_probe)" in value_temp.candidate_text

    index_temp = next(
        probe
        for probe in indexed_probes
        if probe.payload["strategy"] == "indexed-byte-index-temp"
    )
    assert "    int sorted_names_idx_probe;\n" in index_temp.candidate_text
    assert "        sorted_names_idx_probe = j;\n" in index_temp.candidate_text
    assert "GetNameText(mnDiagram_804A076C.sorted_names[sorted_names_idx_probe])" in (
        index_temp.candidate_text
    )

    base_alias = next(
        probe
        for probe in indexed_probes
        if probe.mutator_key == "steer_indexed_byte_base_alias"
        and probe.payload["strategy"] == "indexed-byte-base-alias"
    )
    assert base_alias.payload["strategy"] == "indexed-byte-base-alias"
    assert "    u8* sorted_names_base_probe;\n" in base_alias.candidate_text
    assert (
        "        sorted_names_base_probe = mnDiagram_804A076C.sorted_names;\n"
        in base_alias.candidate_text
    )
    assert "GetNameText(sorted_names_base_probe[j])" in base_alias.candidate_text


def test_indexed_byte_address_temp_generates_consistent_condition_base_alias() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "struct MnDiagramData { u8 sorted_names[25]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "char* GetNameText(int slot);\n"
        "void mnDiagram_SortNamesByKOs(int i) {\n"
        "    u32 totals[25];\n"
        "    int max_idx;\n"
        "    int j;\n"
        "    max_idx = i;\n"
        "    for (j = i + 1; j < 25; j++) {\n"
        "        if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != 0) &&\n"
        "            (totals[mnDiagram_804A076C.sorted_names[max_idx]] <\n"
        "             totals[mnDiagram_804A076C.sorted_names[j]])) {\n"
        "            max_idx = j;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        families=("indexed_byte_address_temp_steering",),
        max_per_family=20,
    )

    base_alias = next(
        probe
        for probe in probes
        if probe.payload["strategy"] == "indexed-byte-base-alias-condition-all-reads"
    )
    assert base_alias.mutator_key == "steer_indexed_byte_base_alias"
    assert "    u8* sorted_names_base_probe;\n" in base_alias.candidate_text
    assert (
        "        sorted_names_base_probe = mnDiagram_804A076C.sorted_names;\n"
        in base_alias.candidate_text
    )
    assert "GetNameText(sorted_names_base_probe[j])" in base_alias.candidate_text
    assert "totals[sorted_names_base_probe[max_idx]]" in base_alias.candidate_text
    assert "totals[sorted_names_base_probe[j]]" in base_alias.candidate_text
    assert "GetNameText(mnDiagram_804A076C.sorted_names" not in base_alias.candidate_text
    assert "totals[mnDiagram_804A076C.sorted_names" not in base_alias.candidate_text
