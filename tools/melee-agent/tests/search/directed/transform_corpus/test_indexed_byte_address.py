"""Tests for non-struct indexed byte-array address-temp steering probes."""
from __future__ import annotations

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
