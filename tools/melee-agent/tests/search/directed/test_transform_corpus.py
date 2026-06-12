"""Tests for the source-transform corpus and probe planner."""
from __future__ import annotations

from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probes,
    plan_transform_experiments,
)


def test_default_corpus_names_required_transform_families() -> None:
    family_ids = {family.family_id for family in DEFAULT_TRANSFORM_FAMILIES}

    assert "condition_split_merge" in family_ids
    assert "declaration_use_boundary" in family_ids
    assert "loop_index_pointer_walk_split" in family_ids
    assert "reload_branch_scope" in family_ids
    assert "lifetime_preserve_shorten" in family_ids
    assert all(family.semantic_risk for family in DEFAULT_TRANSFORM_FAMILIES)
    assert all(family.expected_compiler_effect for family in DEFAULT_TRANSFORM_FAMILIES)


def test_plan_transform_experiments_groups_e7b4_force_phys_clusters() -> None:
    plan = plan_transform_experiments(
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 44: 4, 42: 3, 35: 29, 56: 30, 34: 31},
    )

    assert plan.function == "ftCo_8009E7B4"
    assert plan.source_file == "src/melee/ft/ftcommon.c"
    assert {cluster.cluster_id for cluster in plan.clusters} == {
        "early_flag_reload",
        "late_field_loop_tree",
    }
    early = next(cluster for cluster in plan.clusters if cluster.cluster_id == "early_flag_reload")
    assert early.target_assignments == ("ig58->r4", "ig44->r4", "ig42->r3")
    assert "reload_branch_scope" in early.family_ids
    late = next(cluster for cluster in plan.clusters if cluster.cluster_id == "late_field_loop_tree")
    assert "loop_index_pointer_walk_split" in late.family_ids


def test_generate_transform_probes_materializes_source_edits() -> None:
    source = (
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "    if (fp->x594_b4) {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
        max_per_family=2,
    )

    assert probes
    by_family = {probe.family_id: probe for probe in probes}
    assert "condition_split_merge" in by_family
    assert "} else if (kind != 0) {" in by_family["condition_split_merge"].candidate_text
    assert "lifetime_preserve_shorten" in by_family
    assert by_family["lifetime_preserve_shorten"].source_region
    assert all(probe.target_assignments for probe in probes)


def test_generate_transform_probes_only_uses_target_function_body() -> None:
    source = (
        "void helper(void) {\n"
        "    if (a) {\n"
        "        x = 1;\n"
        "    } else if (b) {\n"
        "        x = 2;\n"
        "    }\n"
        "}\n"
        "void ftCo_8009E7B4(void) {\n"
        "    if (fp->x594_b4) {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
        max_per_family=1,
    )

    assert probes
    assert all(probe.span[0] > source.index("void ftCo_8009E7B4") for probe in probes)
    assert "condition_split_merge" not in {probe.family_id for probe in probes}


def test_generate_transform_probes_returns_empty_when_target_body_is_absent() -> None:
    source = (
        "void helper(void) {\n"
        "    if (a) {\n"
        "        x = 1;\n"
        "    } else if (b) {\n"
        "        x = 2;\n"
        "    }\n"
        "}\n"
        "/// #ftCo_8009E7B4\n"
    )

    probes = generate_transform_probes(
        source,
        function="ftCo_8009E7B4",
        unit="melee/ft/ftcommon",
        force_phys={58: 4, 35: 29},
    )

    assert probes == ()
