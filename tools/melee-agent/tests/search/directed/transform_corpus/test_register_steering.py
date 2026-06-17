"""Tests for the register_steering transform family (transform_corpus.register_steering)."""
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


def test_generate_transform_probes_materializes_mndiagram_coloring_register_steering() -> None:
    source = (
        "void mnDiagram2_Create(void) {\n"
        "    s32 did = 0;\n"
        "    HSD_GObj* mgobj;\n"
        "    s32 i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    s32 i;\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        use(i);\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=3,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert steering
    assert all(probe.mutator_key.startswith("steer_") for probe in steering)
    assert {
        "steer_reorder_local_decls",
        "steer_reuse_loop_counter_scope",
    } <= {probe.mutator_key for probe in steering}
    assert any(
        "s32 i;\n    HSD_GObj* mgobj;" in probe.candidate_text
        for probe in steering
    )
    assert all(probe.target_assignments == ("ig35->r29", "ig58->r4") for probe in steering)
    assert transform_probe_key(steering[0]).startswith(
        "transform-corpus:coloring_register_steering:"
    )


def test_coloring_register_steering_keeps_safe_split_decl_init_probe() -> None:
    source = (
        "void mnDiagram2_Create(void) {\n"
        "    s32 did = 0;\n"
        "    did += 1;\n"
        "    use(did);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=3,
    )

    split = next(
        probe for probe in probes
        if probe.mutator_key == "steer_split_decl_init"
    )
    assert "    s32 did;\n    did = 0;" in split.candidate_text


def test_coloring_register_steering_materializes_concrete_levers_default_budget() -> None:
    source = (
        "void mnDiagram2_Create(s32* a, s32 seed) {\n"
        "    s32 temp;\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    int j;\n"
        "    int i;\n"
        "    rank = seed + 1;\n"
        "    temp = rank;\n"
        "    use(gobj, temp);\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j, temp, gobj);\n"
        "        j++;\n"
        "    } while (j < 2);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=3,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert [probe.mutator_key for probe in steering] == [
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
        "steer_reuse_dead_top_level_loop_counter",
    ]
    assert "HSD_GObj* gobj;\n    s32 temp;\n    s32 rank;" in steering[0].candidate_text
    assert (
        "s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    int j;\n"
        "    int i;\n"
        "    s32 temp;"
    ) in steering[1].candidate_text
    assert "int j;" not in steering[2].candidate_text
    assert "i = 0;" in steering[2].candidate_text
    assert "sink(i, temp, gobj);" in steering[2].candidate_text
    assert "} while (i < 2);" in steering[2].candidate_text
    assert (
        "int i;\n"
        "    rank = seed + 1;"
    ) in steering[2].candidate_text
    assert all(
        probe.target_assignments == ("ig35->r29", "ig58->r4") for probe in steering
    )


def test_coloring_register_steering_skips_node_set_split_synthetic_decl_windows() -> None:
    source = (
        "void mnDiagram_80241E78(void) {\n"
        "    f32 row_offset_split_39_0;\n"
        "    f32 col_offset_split_33_0;\n"
        "    HSD_JObj* jobj;\n"
        "    f32 alpha;\n"
        "    f32 beta;\n"
        "    f32 gamma;\n"
        "    use(jobj, alpha, beta, gamma);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 39: 26},
        families=("coloring_register_steering",),
        max_per_family=8,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert steering
    assert not [
        probe
        for probe in steering
        if "_split_" in source[probe.span[0]:probe.span[1]]
        or "_split_" in str(probe.payload)
    ]
    assert any(
        probe.mutator_key == "steer_rotate_local_decl_window"
        and probe.payload["decl_names"] == ("alpha", "beta", "gamma")
        for probe in steering
    )


def test_coloring_register_steering_rejects_split_decl_init_before_later_decl() -> None:
    source = (
        "void mnDiagram_80241E78(u8 arg1, u8 arg2) {\n"
        "    u8 col = arg1;\n"
        "    u8 row = arg2;\n"
        "    use(col, row);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 39: 26},
        families=("coloring_register_steering",),
        max_per_family=8,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert not [
        probe
        for probe in steering
        if probe.mutator_key == "steer_split_decl_init"
        and probe.payload.get("var") == "col"
    ]
    assert all("    col = arg1;\n    u8 row" not in probe.candidate_text for probe in steering)


def test_coloring_register_steering_skips_generated_fpr_product_temps() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(f32 y_spacing, f32 y_offset, int col, int row) {\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 col_offset_product_fpr;\n"
        "    col_offset_product_fpr = y_spacing * (f32) col;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    row_offset = y_offset * (f32) row;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    use(col_offset, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=16,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert steering
    assert not [
        probe for probe in steering
        if probe.payload.get("product_local") == "col_offset_product_fpr"
        or "col_offset_product_fpr_product_fpr" in probe.candidate_text
    ]
    assert any(
        probe.mutator_key == "steer_fpr_product_temp_split"
        and probe.payload.get("product_local") == "row_offset"
        and "row_offset_product_fpr" in probe.candidate_text
        for probe in steering
    )


def _node_set_delta_payload() -> dict:
    return {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"kind": "local", "expression": "gobj", "name": "gobj"},
                "source_action": "Split gobj before use.",
            },
            {
                "target_ig": 49,
                "current_register": "r29",
                "desired_registers": ["r25"],
                "source": {
                    "kind": "field-load",
                    "expression": "data->is_name_mode",
                    "base_var": "data",
                    "field_offset": 72,
                },
                "source_action": "Split data field load before use.",
            },
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
                "source_action": "Implicit temp cannot bind directly.",
            },
        ],
    }


def _node_set_delta_source() -> str:
    return (
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Data { int pad0; int is_name_mode; int selected; } Data;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj, Data* data) {\n"
        "    int i;\n"
        "    int j;\n"
        "    int selected;\n"
        "    use(gobj);\n"
        "    selected = data->selected;\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(i, selected);\n"
        "    }\n"
        "    j = data->is_name_mode;\n"
        "    sink(gobj, data, j);\n"
        "}\n"
    )


def _generic_node_set_delta_source() -> str:
    return (
        "typedef struct HSD_GObj HSD_GObj;\n"
        "void generic_NodeSet_Create(HSD_GObj* gobj) {\n"
        "    int i;\n"
        "    use(gobj);\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(i, gobj);\n"
        "    }\n"
        "}\n"
    )


def test_node_set_delta_none_preserves_existing_steering_order() -> None:
    source = _node_set_delta_source()

    without_arg = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        max_per_family=3,
    )
    with_none = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        node_set_delta=None,
        max_per_family=3,
    )

    assert [probe.mutator_key for probe in with_none] == [
        probe.mutator_key for probe in without_arg
    ]
    assert [probe.candidate_text for probe in with_none] == [
        probe.candidate_text for probe in without_arg
    ]


def test_node_set_delta_single_and_coupled_probes_precede_blind_steering() -> None:
    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        node_set_delta=_node_set_delta_payload(),
        max_per_family=3,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert steering
    assert steering[0].mutator_key == "steer_node_set_delta_coupled_split"
    assert {probe.mutator_key for probe in steering} >= {
        "steer_node_set_delta_split",
        "steer_node_set_delta_coupled_split",
    }
    assert all("node_set_delta" in probe.payload for probe in steering[:2])
    assert "ig36:r25->r27" in steering[0].target_assignments
    assert "ig49:r29->r25" in steering[0].target_assignments


def test_node_set_delta_enables_steering_family_for_generic_function() -> None:
    probes = generate_transform_probes(
        _generic_node_set_delta_source(),
        function="generic_NodeSet_Create",
        unit="melee/ft/ftgeneric",
        force_phys={12: 27},
        node_set_delta={
            "kind": "node-set-delta",
            "function": "generic_NodeSet_Create",
            "class_id": 0,
            "missing_virtuals": [
                {
                    "target_ig": 12,
                    "current_register": "r25",
                    "desired_registers": ["r27"],
                    "source": {
                        "kind": "local",
                        "expression": "gobj",
                        "name": "gobj",
                    },
                    "source_action": "Split gobj before use.",
                }
            ],
        },
        max_per_family=2,
    )

    assert {
        probe.mutator_key for probe in probes
        if probe.family_id == "coloring_register_steering"
    } >= {"steer_node_set_delta_split"}


def test_node_set_delta_payload_preserves_raw_request_evidence() -> None:
    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        node_set_delta=_node_set_delta_payload(),
        max_per_family=3,
    )

    node_set = next(
        probe for probe in probes
        if probe.mutator_key.startswith("steer_node_set_delta")
    )
    request = node_set.payload["node_set_delta"]["requests"][0]

    assert request["target_ig"] == 36
    assert request["target_reg"] == "r27"
    assert request["var_name"] == "gobj"
    assert request["desired_registers"] == ["r27"]
    assert request["source_action"] == "Split gobj before use."
    assert request["source"] == {
        "kind": "local",
        "expression": "gobj",
        "name": "gobj",
    }


def test_node_set_delta_duplicate_target_ig_uses_bindable_raw_evidence() -> None:
    delta = {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "implicit-temp",
                    "expression": "add r36,r45,r63",
                },
                "source_action": "Implicit temp cannot bind directly.",
            },
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"kind": "local", "expression": "gobj", "name": "gobj"},
                "source_action": "Split bindable gobj before use.",
            },
        ],
    }

    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27},
        node_set_delta=delta,
        max_per_family=2,
    )

    node_set = next(
        probe for probe in probes
        if probe.mutator_key.startswith("steer_node_set_delta")
    )
    request = node_set.payload["node_set_delta"]["requests"][0]

    assert request["target_ig"] == 36
    assert request["var_name"] == "gobj"
    assert request["source_action"] == "Split bindable gobj before use."
    assert request["raw_missing_virtual"]["source"] == {
        "kind": "local",
        "expression": "gobj",
        "name": "gobj",
    }
    assert [
        entry["source_action"] for entry in request["raw_missing_virtuals"]
    ] == [
        "Implicit temp cannot bind directly.",
        "Split bindable gobj before use.",
    ]


def test_node_set_delta_capped_bindable_entries_are_not_marked_unbindable() -> None:
    source = (
        "void mnDiagram2_Create(int* a, int* b, int* c, int* d, int* e) {\n"
        "    use(a, b, c, d, e);\n"
        "}\n"
    )
    missing_virtuals = [
        {
            "target_ig": target_ig,
            "current_register": "r25",
            "desired_registers": ["r27"],
            "source": {"kind": "local", "expression": name, "name": name},
            "source_action": f"Split {name} before use.",
        }
        for target_ig, name in (
            (30, "a"),
            (31, "b"),
            (32, "c"),
            (33, "d"),
            (34, "e"),
        )
    ]

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={30: 27, 31: 27, 32: 27, 33: 27, 34: 27},
        node_set_delta={
            "kind": "node-set-delta",
            "function": "mnDiagram2_Create",
            "class_id": 0,
            "missing_virtuals": missing_virtuals,
        },
        max_per_family=2,
    )

    node_set = next(
        probe for probe in probes
        if probe.mutator_key.startswith("steer_node_set_delta")
    )
    payload = node_set.payload["node_set_delta"]

    assert all(
        entry["target_ig"] != 34
        for entry in payload["skipped_missing_virtuals"]
    )
    capped = payload["capped_missing_virtuals"]
    assert any(
        entry["target_ig"] == 34
        and entry["blocked_reason"] == "request cap exceeded"
        for entry in capped
    )


def test_node_set_delta_dedupes_candidate_text_against_blind_steering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _node_set_delta_source()
    blind_probe = next(
        probe for probe in generate_transform_probes(
            source,
            function="mnDiagram2_Create",
            unit="melee/mn/mndiagram2",
            force_phys={36: 27},
            max_per_family=5,
        )
        if probe.mutator_key == "steer_rotate_local_decl_window"
    )

    def fake_coupled_patches(*_args, **_kwargs):
        return []

    def fake_single_patches(_source_text, _function, request, **_kwargs):
        if request.target_ig != 36:
            return []
        return [
            CandidatePatch(
                candidate_id="duplicate-blind-steering",
                patched_source=blind_probe.candidate_text,
                summary="Duplicate blind steering candidate.",
                touched_ranges=(blind_probe.span,),
                hunk="@@ duplicate @@",
            )
        ]

    import src.mwcc_debug.node_set_split as node_set_split

    monkeypatch.setattr(
        node_set_split,
        "generate_coupled_node_set_split_patches",
        fake_coupled_patches,
    )
    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_single_patches,
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27},
        node_set_delta={
            "kind": "node-set-delta",
            "function": "mnDiagram2_Create",
            "class_id": 0,
            "missing_virtuals": [
                {
                    "target_ig": 36,
                    "current_register": "r25",
                    "desired_registers": ["r27"],
                    "source": {
                        "kind": "local",
                        "expression": "gobj",
                        "name": "gobj",
                    },
                    "source_action": "Split gobj before use.",
                }
            ],
        },
        max_per_family=5,
    )

    duplicates = [
        probe for probe in probes
        if probe.family_id == "coloring_register_steering"
        and probe.candidate_text == blind_probe.candidate_text
    ]
    assert [probe.mutator_key for probe in duplicates] == [
        "steer_node_set_delta_split"
    ]


def test_node_set_delta_reports_unbindable_missing_virtuals() -> None:
    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25, 51: 27},
        node_set_delta=_node_set_delta_payload(),
        max_per_family=3,
    )

    node_set = [
        probe for probe in probes
        if probe.mutator_key.startswith("steer_node_set_delta")
    ]
    assert node_set
    skipped = node_set[0].payload["node_set_delta"]["skipped_missing_virtuals"]
    assert any(entry["target_ig"] == 51 for entry in skipped)
    assert node_set[0].span[0] <= node_set[0].span[1]


def test_node_set_delta_all_unbindable_emits_no_materialized_probes() -> None:
    delta = {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
            }
        ],
    }

    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={51: 27},
        node_set_delta=delta,
        max_per_family=3,
    )

    assert "steer_node_set_delta_split" not in {probe.mutator_key for probe in probes}
    assert "steer_node_set_delta_coupled_split" not in {
        probe.mutator_key for probe in probes
    }


def test_coloring_register_steering_pairs_dead_counters_by_loop_order() -> None:
    source = (
        "void mnDiagram2_Create(void) {\n"
        "    int k;\n"
        "    int j;\n"
        "    int h;\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    for (h = 0; h < 3; h++) {\n"
        "        sink(h);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j);\n"
        "        j++;\n"
        "    } while (j < 2);\n"
        "    k = 0;\n"
        "    do {\n"
        "        sink(k);\n"
        "        k++;\n"
        "    } while (k < 2);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=12,
    )

    dead_reuse = [
        probe
        for probe in probes
        if probe.mutator_key == "steer_reuse_dead_top_level_loop_counter"
    ]
    assert dead_reuse
    first = dead_reuse[0]
    assert first.payload["old_counter"] == "i"
    assert first.payload["later_counter"] == "j"
    assert "int j;" not in first.candidate_text
    assert "i = 0;" in first.candidate_text
    assert "sink(i);" in first.candidate_text
    assert "h = 0;" in first.candidate_text
    assert "k = 0;" in first.candidate_text


def test_coloring_register_steering_widens_byte_local_type() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram2_Create(void) {\n"
        "    u8 scroll;\n"
        "    int threshold;\n"
        "    int offset;\n"
        "    scroll = get_scroll();\n"
        "    threshold = 24;\n"
        "    if ((int) scroll >= threshold) {\n"
        "        offset = scroll - threshold;\n"
        "    } else {\n"
        "        offset = scroll;\n"
        "    }\n"
        "    use(offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={55: 4},
        max_per_family=12,
    )

    widen = next(
        probe for probe in probes
        if probe.mutator_key == "steer_widen_byte_local_type"
    )
    assert widen.payload["var"] == "scroll"
    assert widen.payload["from"] == "u8"
    assert widen.payload["to"] == "int"
    assert widen.payload["span_text"] == "    u8 scroll;"
    assert widen.payload["replacement_text"] == "    int scroll;"
    assert "    int scroll;\n" in widen.candidate_text
    assert "    u8 scroll;\n" not in widen.candidate_text


def test_coloring_register_steering_recomputes_fpr_dependent_product_before_decl_aliases() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_80241E78(u8 arg2) {\n"
        "    void** joint_data;\n"
        "    f32 y_offset;\n"
        "    f32 row_offset;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset_adj;\n"
        "    u8 row = arg2;\n"
        "    row_offset = y_offset * (f32) row;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
        "    use(joint_data, row_offset, row_offset_adj, col_offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=1,
    )

    assert len(probes) == 1
    probe = probes[0]
    assert probe.mutator_key == "steer_fpr_dependent_product_recompute"
    assert probe.payload["strategy"] == "fpr-dependent-product-recompute-first"
    assert (
        "    row_offset_adj = (y_offset * (f32) row) - 1.0f;\n"
        "    row_offset = y_offset * (f32) row;"
    ) in probe.candidate_text
    assert probe.candidate_text.count("f32 ") == source.count("f32 ")


def test_coloring_register_steering_recomputes_rowf_product_same_order_when_budget_allows() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(u8 row) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    use(row_offset, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    recompute = [
        probe
        for probe in probes
        if probe.mutator_key == "steer_fpr_dependent_product_recompute"
    ]
    assert {
        probe.payload["strategy"]
        for probe in recompute
    } >= {
        "fpr-dependent-product-recompute-first",
        "fpr-dependent-product-recompute-same-order",
    }
    assert (
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = (y_offset * rowf) - 0.4f;"
    ) in recompute[1].candidate_text


def test_coloring_register_steering_emits_dependent_product_lifetime_variants() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(u8 row) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    use(row_offset, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in probes
        if probe.mutator_key in {
            "steer_fpr_dependent_product_reuse_temp",
            "steer_fpr_dependent_local_temp_split",
        }
    }
    assert "fpr-dependent-product-reuse-temp" in by_strategy
    assert "fpr-dependent-local-temp-split" in by_strategy

    reuse_temp = by_strategy["fpr-dependent-product-reuse-temp"]
    assert "    f32 row_offset_product_reuse_fpr;\n" in reuse_temp.candidate_text
    assert "    row_offset_product_reuse_fpr = y_offset * rowf;\n" in (
        reuse_temp.candidate_text
    )
    assert "    row_offset = row_offset_product_reuse_fpr;\n" in reuse_temp.candidate_text
    assert (
        "    row_offset_adj = row_offset_product_reuse_fpr - 0.4f;"
        in reuse_temp.candidate_text
    )

    local_split = by_strategy["fpr-dependent-local-temp-split"]
    assert "    f32 row_offset_lifetime_fpr;\n" in local_split.candidate_text
    assert "    row_offset = y_offset * rowf;\n" in local_split.candidate_text
    assert "    row_offset_lifetime_fpr = row_offset;\n" in local_split.candidate_text
    assert "    row_offset_adj = row_offset_lifetime_fpr - 0.4f;" in (
        local_split.candidate_text
    )

    default_budget_probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
    )
    default_budget_strategies = {
        probe.payload["strategy"]
        for probe in default_budget_probes
        if probe.mutator_key in {
            "steer_fpr_dependent_product_reuse_temp",
            "steer_fpr_dependent_local_temp_split",
        }
    }
    assert default_budget_strategies == {
        "fpr-dependent-product-reuse-temp",
        "fpr-dependent-local-temp-split",
    }


def test_coloring_register_steering_emits_case_c_fpr_temp_order_probes() -> None:
    combined_source = (
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(unsigned char row) {\n"
        "    f32 base;\n"
        "    f32 y_offset;\n"
        "    f32 y_spacing;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 col_fpr;\n"
        "    f32 col_offset;\n"
        "    int digit_count;\n"
        "    rowf = (f32) row;\n"
        "    y_offset = HSD_JObjGetTranslationY(jobj2) - base;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    col_fpr = (f32) row;\n"
        "    col_offset = y_spacing * col_fpr;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "}\n"
    )
    split_source = (
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(unsigned char row) {\n"
        "    f32 base;\n"
        "    f32 y_offset;\n"
        "    f32 y_spacing;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 col_fpr;\n"
        "    f32 col_offset;\n"
        "    int digit_count;\n"
        "    rowf = (f32) row;\n"
        "    y_offset = HSD_JObjGetTranslationY(jobj2);\n"
        "    y_offset -= base;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    col_fpr = (f32) row;\n"
        "    col_offset = y_spacing * col_fpr;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "}\n"
    )

    for source in (combined_source, split_source):
        probes = generate_transform_probes(
            source,
            function="mnDiagram_DrawCellNumber",
            unit="melee/mn/mndiagram",
            force_phys={39: 26, 33: 28},
            families=("coloring_register_steering",),
            max_per_family=32,
        )

        by_strategy = {
            probe.payload["strategy"]: probe
            for probe in probes
            if probe.mutator_key == "steer_fpr_case_c_temp_order"
        }
        assert {
            "fpr-case-c-left-operand-temp",
            "fpr-case-c-rhs-owner-temp",
            "fpr-case-c-product-owner-temp",
        } <= set(by_strategy)
        assert all(
            probe.payload["target_local"] == "y_offset"
            for probe in by_strategy.values()
        )
        assert all(
            "    col_offset = y_spacing * col_fpr;\n" in probe.candidate_text
            for probe in by_strategy.values()
        )

        left = by_strategy["fpr-case-c-left-operand-temp"]
        assert "    f32 y_offset_left_fpr;\n" in left.candidate_text
        assert "    y_offset_left_fpr = HSD_JObjGetTranslationY(jobj2);\n" in (
            left.candidate_text
        )
        assert "    y_offset = y_offset_left_fpr - base;\n" in left.candidate_text

        rhs_owner = by_strategy["fpr-case-c-rhs-owner-temp"]
        assert "    f32 y_offset_rhs_fpr;\n" in rhs_owner.candidate_text
        assert (
            "    y_offset_rhs_fpr = HSD_JObjGetTranslationY(jobj2) - base;\n"
            in rhs_owner.candidate_text
        )
        assert "    y_offset = y_offset_rhs_fpr;\n" in rhs_owner.candidate_text

        product_owner = by_strategy["fpr-case-c-product-owner-temp"]
        assert "    f32 y_offset_owner_fpr;\n" in product_owner.candidate_text
        assert "    y_offset_owner_fpr = y_offset;\n" in product_owner.candidate_text
        assert "    row_offset = y_offset_owner_fpr * rowf;\n" in (
            product_owner.candidate_text
        )


@pytest.mark.parametrize(
    ("case", "adjustment"),
    (
        ("indexed rhs", "table[i]"),
        ("member rhs", "obj->x"),
        ("side-effect rhs", "++idx"),
        ("second call rhs", "GetBase()"),
    ),
)
def test_coloring_register_steering_rejects_unsafe_case_c_fpr_temp_order(
    case: str,
    adjustment: str,
) -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(unsigned char row) {\n"
        "    f32 base;\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        f"    y_offset = HSD_JObjGetTranslationY(jobj2) - {adjustment};\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=32,
    )

    assert "steer_fpr_case_c_temp_order" not in {
        probe.mutator_key for probe in probes
    }, case


def test_coloring_register_steering_uses_source_function_aliases() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(u8 row) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    use(row_offset, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        function_aliases=("mnDiagram_80241E78",),
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    strategies = {
        probe.payload["strategy"]
        for probe in probes
        if probe.mutator_key in {
            "steer_fpr_dependent_product_reuse_temp",
            "steer_fpr_dependent_local_temp_split",
        }
    }
    assert strategies == {
        "fpr-dependent-product-reuse-temp",
        "fpr-dependent-local-temp-split",
    }
    assert all("mnDiagram_80241E78" in probe.candidate_text for probe in probes)
    assert all("mnDiagram_DrawCellNumber" not in probe.candidate_text for probe in probes)


def test_coloring_register_steering_handles_repeated_dependent_product() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(u8 row) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = y_offset * rowf - 0.4f;\n"
        "    use(row_offset, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in probes
        if probe.mutator_key in {
            "steer_fpr_dependent_product_reuse_temp",
            "steer_fpr_dependent_local_temp_split",
        }
    }
    assert "fpr-dependent-product-reuse-temp" in by_strategy
    assert "fpr-dependent-local-temp-split" in by_strategy

    reuse_temp = by_strategy["fpr-dependent-product-reuse-temp"]
    assert "    row_offset_product_reuse_fpr = y_offset * rowf;\n" in (
        reuse_temp.candidate_text
    )
    assert "    row_offset = row_offset_product_reuse_fpr;\n" in reuse_temp.candidate_text
    assert "    row_offset_adj = row_offset_product_reuse_fpr - 0.4f;" in (
        reuse_temp.candidate_text
    )

    local_split = by_strategy["fpr-dependent-local-temp-split"]
    assert "    row_offset = y_offset * rowf;\n" in local_split.candidate_text
    assert "    row_offset_lifetime_fpr = row_offset;\n" in local_split.candidate_text
    assert "    row_offset_adj = row_offset_lifetime_fpr - 0.4f;" in (
        local_split.candidate_text
    )


def test_coloring_register_steering_emits_source_bound_fpr_product_variants() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(u8 row, u8 col) {\n"
        "    f32 y_offset;\n"
        "    f32 y_spacing;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 col_offset;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    HSD_JObjSetTranslateX(jobj, row_offset, col_offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    by_key = {probe.mutator_key: probe for probe in probes}
    assert "steer_fpr_product_assignment_order" in by_key
    assert "steer_fpr_product_cast_temp_split" in by_key
    assert "steer_fpr_product_argument_duplicate" in by_key

    assignment_order = by_key["steer_fpr_product_assignment_order"]
    assert assignment_order.payload["strategy"] == "fpr-product-assignment-order"
    assert (
        "    col_offset = y_spacing * (f32) col;\n"
        "    row_offset = y_offset * rowf;"
    ) in assignment_order.candidate_text

    cast_split = by_key["steer_fpr_product_cast_temp_split"]
    assert cast_split.payload["product_local"] == "col_offset"
    assert "    f32 col_fpr;\n" in cast_split.candidate_text
    assert "    col_fpr = (f32) col;\n" in cast_split.candidate_text
    assert "    col_offset = y_spacing * col_fpr;" in cast_split.candidate_text

    duplicate_arg = next(
        probe
        for probe in probes
        if probe.mutator_key == "steer_fpr_product_argument_duplicate"
        and probe.payload["product_local"] == "row_offset"
    )
    assert duplicate_arg.payload["product_local"] == "row_offset"
    assert (
        "HSD_JObjSetTranslateX(jobj, y_offset * rowf, col_offset);"
        in duplicate_arg.candidate_text
    )


def test_coloring_register_steering_emits_product_temp_split_variants() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(u8 row, u8 col) {\n"
        "    f32 y_offset;\n"
        "    f32 y_spacing;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 col_offset;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    HSD_JObjSetTranslateX(jobj, row_offset, col_offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=16,
    )

    split = next(
        probe for probe in probes
        if probe.mutator_key == "steer_fpr_product_temp_split"
        and probe.payload["product_local"] == "row_offset"
    )
    assert split.payload["strategy"] == "fpr-product-temp-split"
    assert split.payload["product_expr"] == "y_offset * rowf"
    assert "    f32 row_offset_product_fpr;\n" in split.candidate_text
    assert "    row_offset_product_fpr = y_offset * rowf;\n" in split.candidate_text
    assert "    row_offset = row_offset_product_fpr;" in split.candidate_text

    paired = next(
        probe for probe in probes
        if probe.mutator_key == "steer_fpr_paired_product_temp_split"
    )
    assert paired.payload["strategy"] == "fpr-paired-product-temp-split"
    assert paired.payload["product_locals"] == ("row_offset", "col_offset")
    assert "    f32 row_offset_product_fpr;\n" in paired.candidate_text
    assert "    f32 col_offset_product_fpr;\n" in paired.candidate_text
    assert "    row_offset_product_fpr = y_offset * rowf;\n" in paired.candidate_text
    assert "    col_offset_product_fpr = y_spacing * (f32) col;\n" in (
        paired.candidate_text
    )
    assert "    row_offset = row_offset_product_fpr;\n" in paired.candidate_text
    assert "    col_offset = col_offset_product_fpr;" in paired.candidate_text


def test_coloring_register_steering_composes_fixed_product_temp_with_dependent_row_variants() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(u8 row, u8 col) {\n"
        "    f32 y_offset;\n"
        "    f32 y_spacing;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 col_offset;\n"
        "    rowf = (f32) row;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=32,
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in probes
        if probe.mutator_key == "steer_fpr_product_temp_plus_dependent"
    }
    assert {
        "fpr-product-temp-plus-dependent-recompute-first",
        "fpr-product-temp-plus-dependent-product-reuse-temp",
        "fpr-product-temp-plus-dependent-local-temp-split",
        "fpr-product-temp-plus-dependent-call-expr-duplicate",
        "fpr-product-temp-plus-dependent-call-temp-split",
    } <= set(by_strategy)

    reuse_temp = by_strategy["fpr-product-temp-plus-dependent-product-reuse-temp"]
    assert reuse_temp.payload["fixed_product_local"] == "col_offset"
    assert reuse_temp.payload["product_local"] == "row_offset"
    assert reuse_temp.payload["dependent_local"] == "row_offset_adj"
    assert "    f32 col_offset_product_fpr;\n" in reuse_temp.candidate_text
    assert "    f32 row_offset_product_reuse_fpr;\n" in reuse_temp.candidate_text
    assert "    col_offset_product_fpr = y_spacing * (f32) col;\n" in (
        reuse_temp.candidate_text
    )
    assert "    col_offset = col_offset_product_fpr;\n" in reuse_temp.candidate_text
    assert "    row_offset_product_reuse_fpr = y_offset * rowf;\n" in (
        reuse_temp.candidate_text
    )
    assert "    row_offset = row_offset_product_reuse_fpr;\n" in (
        reuse_temp.candidate_text
    )
    assert "    row_offset_adj = row_offset_product_reuse_fpr - 0.4f;" in (
        reuse_temp.candidate_text
    )

    local_split = by_strategy["fpr-product-temp-plus-dependent-local-temp-split"]
    assert "    f32 row_offset_lifetime_fpr;\n" in local_split.candidate_text
    assert "    row_offset_lifetime_fpr = row_offset;\n" in (
        local_split.candidate_text
    )
    assert "    row_offset_adj = row_offset_lifetime_fpr - 0.4f;" in (
        local_split.candidate_text
    )

    call_expr = by_strategy["fpr-product-temp-plus-dependent-call-expr-duplicate"]
    assert call_expr.payload["fixed_product_local"] == "col_offset"
    assert call_expr.payload["product_local"] == "row_offset"
    assert call_expr.payload["dependent_local"] == "row_offset_adj"
    assert "    f32 col_offset_product_fpr;\n" in call_expr.candidate_text
    assert "    col_offset_product_fpr = y_spacing * (f32) col;\n" in (
        call_expr.candidate_text
    )
    assert "    HSD_JObjSetTranslateY(jobj, y_offset * rowf);\n" in (
        call_expr.candidate_text
    )
    assert "    HSD_JObjSetTranslateY(jobj, (y_offset * rowf) - 0.4f);\n" in (
        call_expr.candidate_text
    )

    call_temp = by_strategy["fpr-product-temp-plus-dependent-call-temp-split"]
    assert "    f32 row_offset_call_fpr;\n" in call_temp.candidate_text
    assert "    f32 row_offset_adj_call_fpr;\n" in call_temp.candidate_text
    assert "    row_offset_call_fpr = y_offset * rowf;\n" in (
        call_temp.candidate_text
    )
    assert "    HSD_JObjSetTranslateY(jobj, row_offset_call_fpr);\n" in (
        call_temp.candidate_text
    )
    assert "    row_offset_adj_call_fpr = row_offset - 0.4f;\n" in (
        call_temp.candidate_text
    )
    assert "    HSD_JObjSetTranslateY(jobj, row_offset_adj_call_fpr);\n" in (
        call_temp.candidate_text
    )


def test_coloring_register_steering_collapses_simple_fpr_lifetime_alias_for_call_variants() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(u8 row, u8 col) {\n"
        "    f32 y_offset;\n"
        "    f32 y_spacing;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_lifetime_fpr;\n"
        "    f32 row_offset_adj;\n"
        "    f32 col_offset;\n"
        "    rowf = (f32) row;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_lifetime_fpr = row_offset;\n"
        "    row_offset_adj = row_offset_lifetime_fpr - 0.4f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset);\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_DrawCellNumber",
        unit="melee/mn/mndiagram",
        force_phys={39: 26, 33: 28},
        families=("coloring_register_steering",),
        max_per_family=32,
    )

    by_strategy = {
        probe.payload["strategy"]: probe
        for probe in probes
        if probe.mutator_key == "steer_fpr_product_temp_plus_dependent"
    }
    assert {
        "fpr-product-temp-plus-dependent-call-expr-duplicate",
        "fpr-product-temp-plus-dependent-call-temp-split",
    } <= set(by_strategy)

    call_expr = by_strategy["fpr-product-temp-plus-dependent-call-expr-duplicate"]
    assert call_expr.payload["product_local"] == "row_offset"
    assert call_expr.payload["dependent_local"] == "row_offset_adj"
    assert "    HSD_JObjSetTranslateY(jobj, y_offset * rowf);\n" in (
        call_expr.candidate_text
    )
    assert "    HSD_JObjSetTranslateY(jobj, (y_offset * rowf) - 0.4f);\n" in (
        call_expr.candidate_text
    )

    call_temp = by_strategy["fpr-product-temp-plus-dependent-call-temp-split"]
    assert "    row_offset_adj_call_fpr = row_offset - 0.4f;\n" in (
        call_temp.candidate_text
    )


@pytest.mark.parametrize(
    ("case", "body"),
    (
        (
            "non-fpr local",
            "    int row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = row * col;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "declaration initializer",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    f32 row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "integer product operands without fpr proof",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    int row;\n"
            "    int col;\n"
            "    row_offset = row * col;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "self product operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = row_offset * y_offset;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "dependent product operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * row_offset_adj;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "volatile cast operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    volatile int row;\n"
            "    row_offset = y_offset * (f32) row;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "unproven cast operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * (f32) row;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "unproven bare operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * row;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "non-adjacent",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    use(row_offset);\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "nested statements",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        row_offset = y_offset * rowf;\n"
            "        row_offset_adj = row_offset - 1.0f;\n"
            "    }\n",
        ),
        (
            "call operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * get_rowf();\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "member operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * data->rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "indexed operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    f32 row_values[4];\n"
            "    int i;\n"
            "    row_offset = y_offset * row_values[i];\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "dependent expression with multiple source-local uses",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset + rowf - 1.0f;\n",
        ),
        (
            "address taken",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n"
            "    use(&row_offset);\n",
        ),
        (
            "synthetic name",
            "    f32 row_offset_split_33_0;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset_split_33_0 = y_offset * rowf;\n"
            "    row_offset_adj = row_offset_split_33_0 - 1.0f;\n",
        ),
        (
            "shadowed",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        f32 row_offset;\n"
            "        use(row_offset);\n"
            "    }\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "multi-declarator duplicate target",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    f32 row_offset, other;\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "nested long multi-declarator target shadow",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        long row_offset, other;\n"
            "        use(other);\n"
            "    }\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "nested struct multi-declarator target shadow",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        struct Foo row_offset, other;\n"
            "        use(other);\n"
            "    }\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "nested typedef multi-declarator target shadow",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        Foo row_offset, other;\n"
            "        use(other);\n"
            "    }\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "nested function pointer target shadow",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        void (*row_offset)(void);\n"
            "        use(row_offset);\n"
            "    }\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "macro-like target declaration",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    DECL_F32(row_offset);\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "preprocessor",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "#if 1\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n"
            "#endif\n",
        ),
        (
            "preprocessor elsewhere in body",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "#define ROW_SCALE 1\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
    ),
)
def test_coloring_register_steering_rejects_unsafe_fpr_product_recompute(
    case: str,
    body: str,
) -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(void) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        f"{body}"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    dependent_product_keys = {
        "steer_fpr_dependent_product_recompute",
        "steer_fpr_dependent_product_reuse_temp",
        "steer_fpr_dependent_local_temp_split",
    }
    assert dependent_product_keys.isdisjoint({probe.mutator_key for probe in probes}), case


def test_coloring_register_steering_rejects_volatile_parameter_bare_operand() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(volatile int row) {\n"
        "    f32 y_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    row_offset = y_offset * row;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    dependent_product_keys = {
        "steer_fpr_dependent_product_recompute",
        "steer_fpr_dependent_product_reuse_temp",
        "steer_fpr_dependent_local_temp_split",
    }
    assert dependent_product_keys.isdisjoint({probe.mutator_key for probe in probes})


def test_steer_fpr_dependent_product_recompute_rejects_stale_span() -> None:
    source = (
        "void f(void) {\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
        "}\n"
    )
    anchor = Anchor(
        mutator_key="steer_fpr_dependent_product_recompute",
        span=(source.index("    row_offset"), source.index("}\n")),
        payload={
            "span_text": "    missing = y_offset * rowf;",
            "replacement_text": "    row_offset_adj = (y_offset * rowf) - 1.0f;",
        },
    )

    assert apply_mutator("steer_fpr_dependent_product_recompute", anchor, source) is None


def test_coloring_register_steering_rejects_address_taken_byte_widening() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram2_Create(void) {\n"
        "    u8 scroll;\n"
        "    use(&scroll);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={55: 4},
        max_per_family=12,
    )

    assert "steer_widen_byte_local_type" not in {
        probe.mutator_key for probe in probes
    }


def test_coloring_register_steering_rejects_nested_byte_widening() -> None:
    source = (
        "typedef signed char s8;\n"
        "void mnDiagram2_Create(void) {\n"
        "    if (ready()) {\n"
        "        s8 scroll;\n"
        "        use(scroll);\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={55: 4},
        max_per_family=12,
    )

    assert "steer_widen_byte_local_type" not in {
        probe.mutator_key for probe in probes
    }


def test_coloring_register_steering_rejects_broad_declaration_shapes() -> None:
    sources = (
        (
            "void mnDiagram2_Create(void) {\n"
            "    const s32 limit = 3;\n"
            "    static s32 cache = 0;\n"
            "    s32 count;\n"
            "    sink(count);\n"
            "}\n"
        ),
        (
            "void mnDiagram2_Create(void) {\n"
            "#if ENABLE_DIAGRAM\n"
            "    s32 count = 0;\n"
            "#endif\n"
            "    sink(count);\n"
            "}\n"
        ),
        (
            "void mnDiagram2_Create(void) {\n"
            "    s32 count;\n"
            "    {\n"
            "    s32 count;\n"
            "    }\n"
            "    sink(count);\n"
            "}\n"
        ),
    )

    for source in sources:
        probes = generate_transform_probes(
            source,
            function="mnDiagram2_Create",
            unit="melee/mn/mndiagram2",
            force_phys={58: 4},
            max_per_family=5,
        )

        assert "coloring_register_steering" not in {
            probe.family_id for probe in probes
        }


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "preprocessor body",
            (
                "void mnDiagram2_Create(s32* a, s32* b) {\n"
                "#if ENABLE_DIAGRAM\n"
                "    s32 temp;\n"
                "#endif\n"
                "    s32 rank;\n"
                "    HSD_GObj* gobj;\n"
                "    rank = 1;\n"
                "    temp = rank;\n"
                "}\n"
            ),
        ),
        (
            "qualified declaration window",
            (
                "void mnDiagram2_Create(void) {\n"
                "    const s32 temp;\n"
                "    s32 rank;\n"
                "    HSD_GObj* gobj;\n"
                "    rank = 1;\n"
                "}\n"
            ),
        ),
        (
            "aggregate splits the supported run",
            (
                # #699: an aggregate-by-value BETWEEN supported decls splits them
                # into length-1 runs, so no reorder/demote anchor spans it.
                "typedef struct Vec3 Vec3;\n"
                "void mnDiagram2_Create(void) {\n"
                "    s32 rank;\n"
                "    Vec3 pos;\n"
                "    s32 count;\n"
                "    rank = 1;\n"
                "    count = 2;\n"
                "}\n"
            ),
        ),
        (
            "duplicate exact declaration window",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "    s32 rank;\n"
                "    HSD_GObj* gobj;\n"
                "    use(temp, rank, gobj);\n"
                "    s32 temp;\n"
                "    s32 rank;\n"
                "    HSD_GObj* gobj;\n"
                "    use(temp, rank, gobj);\n"
                "}\n"
            ),
        ),
        (
            "demote across label",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "again:\n"
                "    temp = 1;\n"
                "}\n"
            ),
        ),
        (
            "demote across goto",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "    goto done;\n"
                "    temp = 1;\n"
                "done:\n"
                "    sink(temp);\n"
                "}\n"
            ),
        ),
        (
            "demote across macro looking statement",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "    HSD_ASSERT(1);\n"
                "    temp = 1;\n"
                "}\n"
            ),
        ),
        (
            "demote across nested block",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "    if (flag) {\n"
                "        sink(flag);\n"
                "    }\n"
                "    temp = 1;\n"
                "}\n"
            ),
        ),
        (
            "demote across unbraced if",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "    if (flag)\n"
                "        temp = 1;\n"
                "}\n"
            ),
        ),
        (
            "demote across unbraced for",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 temp;\n"
                "    for (j = 0; j < 1; j++)\n"
                "        temp = 1;\n"
                "}\n"
            ),
        ),
        (
            "nested loop reuse",
            (
                "void mnDiagram2_Create(s32* a, s32* b) {\n"
                "    s32 i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "        for (i = 0; i < 2; i++) {\n"
                "            sink(b[i]);\n"
                "        }\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "counter member access in loop",
            (
                "void mnDiagram2_Create(s32* a, Holder* obj) {\n"
                "    s32 i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "    }\n"
                "    for (i = 0; i < 2; i++) {\n"
                "        sink(obj->i);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "counter string literal in loop",
            (
                "void mnDiagram2_Create(s32* a) {\n"
                "    s32 i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "    }\n"
                "    for (i = 0; i < 2; i++) {\n"
                "        OSReport(\"i=%d\", i);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "counter comment in loop",
            (
                "void mnDiagram2_Create(s32* a) {\n"
                "    s32 i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "    }\n"
                "    for (i = 0; i < 2; i++) {\n"
                "        sink(i); // i is reused here\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "counter use after later loop",
            (
                "void mnDiagram2_Create(s32* a, s32* b) {\n"
                "    s32 i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "    }\n"
                "    for (i = 0; i < 2; i++) {\n"
                "        sink(b[i]);\n"
                "    }\n"
                "    sink(i);\n"
                "}\n"
            ),
        ),
        (
            "counter address-take",
            (
                "void mnDiagram2_Create(s32* a, s32* b) {\n"
                "    s32 i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "    }\n"
                "    for (i = 0; i < 2; i++) {\n"
                "        sink(&i);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "generated split name collision",
            (
                "void mnDiagram2_Create(s32* a, s32* b) {\n"
                "    s32 i;\n"
                "    s32 i_1 = 0;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(a[i]);\n"
                "    }\n"
                "    for (i = 0; i < 2; i++) {\n"
                "        sink(b[i]);\n"
                "    }\n"
                "    sink(i_1);\n"
                "}\n"
            ),
        ),
    ),
)
def test_coloring_register_steering_rejects_unsafe_concrete_levers(
    case: str,
    source: str,
) -> None:
    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=12,
    )

    assert not (
        {
            "steer_rotate_local_decl_window",
            "steer_demote_local_decl_to_first_use",
            "steer_split_reused_loop_counter",
        }
        & {probe.mutator_key for probe in probes}
    ), case


def test_coloring_register_steering_allows_run_beside_aggregate() -> None:
    # #699: a present-but-untouched aggregate-by-value decl must no longer
    # suppress the WHOLE family (the old function-level bail). The clean
    # [rank, gobj] run beside `Vec3 pos;` yields reorder/demote anchors, and the
    # per-anchor span filter guarantees no candidate moves/mutates the aggregate.
    source = (
        "typedef struct Vec3 Vec3;\n"
        "void mnDiagram2_Create(void) {\n"
        "    Vec3 pos;\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    rank = 1;\n"
        "}\n"
    )
    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=12,
    )
    steering = [p for p in probes if p.family_id == "coloring_register_steering"]
    # The demote mutator is produced ONLY by the gated iterator; asserting it
    # specifically (not just a non-empty family, which the separate ungated
    # reorder iterator also fills) is the true regression guard against
    # re-introducing the function-level bail.
    assert "steer_demote_local_decl_to_first_use" in {
        probe.mutator_key for probe in steering
    }, "gate relaxation should yield the demote probe beside an aggregate"
    # safety: every candidate keeps `Vec3 pos;` exactly in place.
    for probe in steering:
        assert "    Vec3 pos;\n" in probe.candidate_text


@pytest.mark.parametrize(
    ("case", "source"),
    (
        (
            "old counter used in later loop",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(i, j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "later counter used before prelude",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    sink(j);\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "either counter used after later loop",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "    sink(i, j);\n"
                "}\n"
            ),
        ),
        (
            "counter in comment",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j); // i must not be rewritten here\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "member access",
            (
                "void mnDiagram2_Create(Holder* obj) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(obj->i, j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "parenthesized address-take",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(&(j));\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "statement between prelude and do",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    sink(0);\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "same-line label between loops",
            (
                "void mnDiagram2_Create(int flag) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "label: sink(flag);\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int i;\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested multi-declarator shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int j, x;\n"
                "        sink(j, x);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested call-initialized later shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int j = make();\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested parenthesized old shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int i = (0);\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested array later shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int j[3];\n"
                "        sink(j[0]);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested qualified later shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        volatile int j;\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested reordered-qualified old shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int volatile i;\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested storage-class later shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        register int j;\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested function-pointer later shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int (*j)(void);\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "nested array-pointer old shadow",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        int (*i)[3];\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "earlier loop has break when later decl follows loop",
            (
                "void mnDiagram2_Create(int flag) {\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        if (flag) {\n"
                "            break;\n"
                "        }\n"
                "        sink(i);\n"
                "    }\n"
                "    int j;\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "earlier loop has address-take when later decl follows loop",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(&(i));\n"
                "    }\n"
                "    int j;\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "old counter address taken before earlier loop",
            (
                "void mnDiagram2_Create(int* p) {\n"
                "    int i;\n"
                "    p = &i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    int j;\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "    sink(*p);\n"
                "}\n"
            ),
        ),
        (
            "later prelude reads later counter",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = j + 1;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "later for init reads later counter",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    for (j = j + 1; j < 2; j++) {\n"
                "        sink(j);\n"
                "    }\n"
                "}\n"
            ),
        ),
        (
            "return barrier between loops",
            (
                "void mnDiagram2_Create(int flag) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    if (flag) {\n"
                "        return;\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "goto barrier between loops",
            (
                "void mnDiagram2_Create(int flag) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    if (flag) {\n"
                "        goto done;\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "done:\n"
                "    return;\n"
                "}\n"
            ),
        ),
        (
            "switch barrier between loops",
            (
                "void mnDiagram2_Create(int flag) {\n"
                "    int j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    switch (flag) {\n"
                "    case 0:\n"
                "        sink(0);\n"
                "        break;\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "initialized old counter",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j;\n"
                "    int i = 0;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "initialized later counter",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j = 0;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "mismatched counter types",
            (
                "void mnDiagram2_Create(void) {\n"
                "    s32 j;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
        (
            "multi declarator later counter",
            (
                "void mnDiagram2_Create(void) {\n"
                "    int j, k;\n"
                "    int i;\n"
                "    for (i = 0; i < 3; i++) {\n"
                "        sink(i);\n"
                "    }\n"
                "    j = 0;\n"
                "    do {\n"
                "        sink(j);\n"
                "        j++;\n"
                "    } while (j < 2);\n"
                "}\n"
            ),
        ),
    ),
)
def test_coloring_register_steering_rejects_unsafe_dead_counter_reuse(
    case: str,
    source: str,
) -> None:
    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=12,
    )

    assert "steer_reuse_dead_top_level_loop_counter" not in {
        probe.mutator_key for probe in probes
    }, case


def test_coloring_register_steering_rejects_initialized_decl_window_rotation() -> None:
    source = (
        "void mnDiagram2_Create(void) {\n"
        "    s32 temp = 0;\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    rank = temp + 1;\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
        max_per_family=12,
    )

    assert "steer_rotate_local_decl_window" not in {
        probe.mutator_key for probe in probes
    }
