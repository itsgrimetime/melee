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
        max_per_family=12,
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
        max_per_family=12,
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


def test_indexed_byte_address_temp_generates_condition_all_read_value_temps() -> None:
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

    value_temps = next(
        probe
        for probe in probes
        if probe.payload["strategy"] == "indexed-byte-condition-all-read-value-temps"
    )
    assert value_temps.mutator_key == "steer_indexed_byte_value_temp"
    assert "    u8 sorted_names_probe;\n" in value_temps.candidate_text
    assert "    u8 sorted_names_probe_2;\n" in value_temps.candidate_text
    assert (
        "        sorted_names_probe = mnDiagram_804A076C.sorted_names[j];\n"
        in value_temps.candidate_text
    )
    assert (
        "        sorted_names_probe_2 = mnDiagram_804A076C.sorted_names[max_idx];\n"
        in value_temps.candidate_text
    )
    assert "GetNameText(sorted_names_probe)" in value_temps.candidate_text
    assert "totals[sorted_names_probe_2]" in value_temps.candidate_text
    assert "totals[sorted_names_probe]" in value_temps.candidate_text
    assert "GetNameText(mnDiagram_804A076C.sorted_names" not in (
        value_temps.candidate_text
    )
    assert "totals[mnDiagram_804A076C.sorted_names" not in (
        value_temps.candidate_text
    )


def test_indexed_byte_address_temp_handles_pointer_base_conditions() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "char* GetNameText(int slot);\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, int i) {\n"
        "    u32 totals[25];\n"
        "    int max_idx;\n"
        "    int j;\n"
        "    max_idx = i;\n"
        "    for (j = i + 1; j < 25; j++) {\n"
        "        if ((GetNameText(sorted_names[j]) != 0) &&\n"
        "            (totals[sorted_names[max_idx]] < totals[sorted_names[j]])) {\n"
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

    strategies = {probe.payload["strategy"] for probe in probes}
    assert "indexed-byte-base-alias-condition-all-reads" in strategies
    assert "indexed-byte-condition-all-read-value-temps" in strategies


def test_indexed_byte_address_temp_emits_sort_ig34_lifetime_and_index_levers() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "typedef struct HSD_Text HSD_Text;\n"
        "struct MnDiagramData { u8 sorted_names[120]; HSD_Text* text[120]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "char* GetNameText(int slot);\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    struct MnDiagramData* assets = (struct MnDiagramData*) &mnDiagram_804A076C;\n"
        "    u32 totals[120];\n"
        "    int max_idx;\n"
        "    int j;\n"
        "    int i;\n"
        "    int n;\n"
        "    HSD_Text* tp;\n"
        "    u8* dst_iter;\n"
        "    u8* dst = assets->sorted_names;\n"
        "    HSD_Text** text = assets->text;\n"
        "    dst_iter = dst;\n"
        "    tp = *text;\n"
        "    for (n = 0; n < 120; n++, dst_iter++, tp++) {\n"
        "        *dst_iter = (u8) n;\n"
        "    }\n"
        "    for (i = 0; i < 119; i++) {\n"
        "        max_idx = i;\n"
        "        for (j = i + 1; j < 120; j++) {\n"
        "            if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != 0) &&\n"
        "                (totals[mnDiagram_804A076C.sorted_names[max_idx]] <\n"
        "                 totals[mnDiagram_804A076C.sorted_names[j]])) {\n"
        "                max_idx = j;\n"
        "            }\n"
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
        max_per_family=40,
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in probes
        if "strategy" in probe.payload
    }
    assert {
        "indexed-byte-init-pointer-alias",
        "indexed-byte-condition-index-aliases",
        "indexed-byte-totals-index-int-temps",
    } <= set(by_strategy)

    init_alias = by_strategy["indexed-byte-init-pointer-alias"]
    assert init_alias.mutator_key == "steer_indexed_byte_init_pointer_alias"
    assert "    u8* dst_iter_init_probe;\n" in init_alias.candidate_text
    assert "    dst_iter_init_probe = dst;\n" in init_alias.candidate_text
    assert "    dst_iter = dst_iter_init_probe;\n" in init_alias.candidate_text

    index_aliases = by_strategy["indexed-byte-condition-index-aliases"]
    assert index_aliases.mutator_key == "steer_indexed_byte_condition_index_alias"
    assert "    int sorted_names_j_idx_probe;\n" in index_aliases.candidate_text
    assert "    int sorted_names_max_idx_idx_probe;\n" in (
        index_aliases.candidate_text
    )
    assert "        sorted_names_j_idx_probe = j;\n" in index_aliases.candidate_text
    assert "        sorted_names_max_idx_idx_probe = max_idx;\n" in (
        index_aliases.candidate_text
    )
    assert "mnDiagram_804A076C.sorted_names[sorted_names_j_idx_probe]" in (
        index_aliases.candidate_text
    )
    assert "mnDiagram_804A076C.sorted_names[sorted_names_max_idx_idx_probe]" in (
        index_aliases.candidate_text
    )

    totals_temps = by_strategy["indexed-byte-totals-index-int-temps"]
    assert totals_temps.mutator_key == "steer_indexed_byte_totals_index_temp"
    assert "    int sorted_names_totals_idx_probe;\n" in totals_temps.candidate_text
    assert "    int sorted_names_totals_idx_probe_2;\n" in (
        totals_temps.candidate_text
    )
    assert (
        "        sorted_names_totals_idx_probe = "
        "mnDiagram_804A076C.sorted_names[max_idx];\n"
    ) in totals_temps.candidate_text
    assert (
        "        sorted_names_totals_idx_probe_2 = "
        "mnDiagram_804A076C.sorted_names[j];\n"
    ) in totals_temps.candidate_text
    assert "totals[sorted_names_totals_idx_probe]" in totals_temps.candidate_text
    assert "totals[sorted_names_totals_idx_probe_2]" in totals_temps.candidate_text


def test_indexed_byte_address_temp_emits_sort_loop_shape_and_value_probes() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "struct MnDiagramData { u8 sorted_names[120]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "char* GetNameText(int slot);\n"
        "u32 SumNameKOs(int slot);\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    struct MnDiagramData* assets = (struct MnDiagramData*) &mnDiagram_804A076C;\n"
        "    u32 totals[120];\n"
        "    int max_idx;\n"
        "    int j;\n"
        "    int i;\n"
        "    int n;\n"
        "    u32* tp;\n"
        "    u8* dst_iter;\n"
        "    u8* dst = assets->sorted_names;\n"
        "    dst_iter = dst;\n"
        "    tp = totals;\n"
        "    for (n = 0; n < 120; n++, dst_iter++, tp++) {\n"
        "        *dst_iter = (u8) n;\n"
        "        *tp = SumNameKOs(n & 0xFF);\n"
        "    }\n"
        "    for (i = 0; i < 119; i++) {\n"
        "        max_idx = i;\n"
        "        for (j = i + 1; j < 120; j++) {\n"
        "            if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != 0) &&\n"
        "                (totals[mnDiagram_804A076C.sorted_names[max_idx]] <\n"
        "                 totals[mnDiagram_804A076C.sorted_names[j]])) {\n"
        "                max_idx = j;\n"
        "            }\n"
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
        max_per_family=80,
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in probes
        if "strategy" in probe.payload
    }
    assert {
        "indexed-byte-init-loop-split",
        "indexed-byte-direct-global-dst",
        "indexed-byte-max-current-value-temp",
    } <= set(by_strategy)

    loop_split = by_strategy["indexed-byte-init-loop-split"]
    assert loop_split.mutator_key == "steer_indexed_byte_init_loop_split"
    assert "    for (n = 0; n < 120; n++, dst_iter++) {\n" in (
        loop_split.candidate_text
    )
    assert "        *dst_iter = (u8) n;\n" in loop_split.candidate_text
    assert "    for (n = 0; n < 120; n++, tp++) {\n" in loop_split.candidate_text
    assert "        *tp = SumNameKOs(n & 0xFF);\n" in loop_split.candidate_text

    direct_global = by_strategy["indexed-byte-direct-global-dst"]
    assert direct_global.mutator_key == "steer_indexed_byte_direct_global_dst"
    assert "    u8* dst = mnDiagram_804A076C.sorted_names;\n" in (
        direct_global.candidate_text
    )
    assert "    u8* dst = assets->sorted_names;\n" not in direct_global.candidate_text

    max_value = by_strategy["indexed-byte-max-current-value-temp"]
    assert max_value.mutator_key == "steer_indexed_byte_max_current_value_temp"
    assert "    u8 sorted_names_max_value_probe;\n" in max_value.candidate_text
    assert (
        "            sorted_names_max_value_probe = "
        "mnDiagram_804A076C.sorted_names[max_idx];\n"
    ) in max_value.candidate_text
    assert "totals[sorted_names_max_value_probe]" in max_value.candidate_text


def test_indexed_byte_address_temp_emits_implicit_address_case_c_probes() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "struct MnDiagramData { u8 sorted_names[120]; };\n"
        "extern struct MnDiagramData mnDiagram_804A076C;\n"
        "u32 mnDiagram_SumNameKOs(int slot);\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    struct MnDiagramData* assets = (struct MnDiagramData*) &mnDiagram_804A076C;\n"
        "    u32 totals[120];\n"
        "    u8* dst_iter;\n"
        "    u8* dst = assets->sorted_names;\n"
        "    u32* tp;\n"
        "    int i;\n"
        "    int n;\n"
        "    u8 temp;\n"
        "    dst_iter = dst;\n"
        "    tp = totals;\n"
        "    for (n = 0; n < 120; n++, dst_iter++, tp++) {\n"
        "        *dst_iter = (u8) n;\n"
        "        *tp = mnDiagram_SumNameKOs(n & 0xFF);\n"
        "    }\n"
        "    dst[i] = temp;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        families=("indexed_byte_address_temp_steering",),
        max_per_family=24,
    )

    indexed_probes = [
        probe
        for probe in probes
        if probe.family_id == "indexed_byte_address_temp_steering"
    ]
    strategies = [
        probe.payload["strategy"]
        for probe in indexed_probes
        if "strategy" in probe.payload
    ]
    assert {
        "indexed-byte-implicit-direct-store-base",
        "indexed-byte-implicit-store-index-temp",
        "indexed-byte-implicit-init-loop-indexed-store",
    } <= set(strategies)
    assert strategies.index("indexed-byte-implicit-direct-store-base") < (
        strategies.index("indexed-byte-implicit-init-loop-indexed-store")
    )
    assert strategies.index("indexed-byte-implicit-store-index-temp") < (
        strategies.index("indexed-byte-implicit-init-loop-indexed-store")
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in indexed_probes
        if "strategy" in probe.payload
    }

    direct_store = by_strategy["indexed-byte-implicit-direct-store-base"]
    assert (
        direct_store.mutator_key
        == "steer_indexed_byte_implicit_direct_store_base"
    )
    assert "    mnDiagram_804A076C.sorted_names[i] = temp;" in (
        direct_store.candidate_text
    )
    assert "    dst[i] = temp;" not in direct_store.candidate_text
    assert "&mnDiagram_804A076C.sorted_names[i]" not in direct_store.candidate_text

    index_temp = by_strategy["indexed-byte-implicit-store-index-temp"]
    assert (
        index_temp.mutator_key == "steer_indexed_byte_implicit_store_index_temp"
    )
    assert "    int sorted_names_store_idx_probe;\n" in index_temp.candidate_text
    assert "    sorted_names_store_idx_probe = i;\n" in index_temp.candidate_text
    assert "    dst[sorted_names_store_idx_probe] = temp;" in (
        index_temp.candidate_text
    )
    assert "&mnDiagram_804A076C.sorted_names[i]" not in index_temp.candidate_text

    loop_rewrite = by_strategy["indexed-byte-implicit-init-loop-indexed-store"]
    assert (
        loop_rewrite.mutator_key
        == "steer_indexed_byte_implicit_init_loop_indexed_store"
    )
    assert "    tp = totals;\n" in loop_rewrite.candidate_text
    assert "    for (n = 0; n < 120; n++, tp++) {\n" in (
        loop_rewrite.candidate_text
    )
    assert "        dst[n] = (u8) n;\n" in loop_rewrite.candidate_text
    assert "        *tp = mnDiagram_SumNameKOs(n & 0xFF);\n" in (
        loop_rewrite.candidate_text
    )
    assert "n++, dst_iter++, tp++" not in loop_rewrite.candidate_text
    assert "    dst_iter = dst;\n" not in loop_rewrite.candidate_text
    assert "&mnDiagram_804A076C.sorted_names[i]" not in (
        loop_rewrite.candidate_text
    )
