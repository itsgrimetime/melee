from __future__ import annotations

from src.search.directed.transform_corpus.orchestrator import (
    RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID,
    generate_transform_probe_report,
)


def _suggest_payload() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "mode": "discover",
        "register_class": "gpr",
        "pairs": [
            {
                "from": 34,
                "to": 40,
                "register_class": "gpr",
                "priority_class": "register-reuse",
                "ir_facts": {
                    "from": {
                        "virtual": 34,
                        "first_def": {
                            "block": 13,
                            "opcode": "addi",
                            "operands": "r34,r37,4",
                        },
                        "bridge": {
                            "var": "dst_iter",
                            "line": 5,
                            "confidence": "low-confidence",
                        },
                    },
                    "to": {
                        "virtual": 40,
                        "first_def": {
                            "block": 1,
                            "opcode": "addi",
                            "operands": "r40,r37,4",
                        },
                        "bridge": {
                            "var": "mirror_iter",
                            "line": 6,
                            "confidence": "low-confidence",
                        },
                    },
                },
                "suggestions": [
                    {
                        "pattern": "common-subexpr",
                        "summary": (
                            "r34 and r40 are computed by identical IR ops "
                            "(addi r37,4)"
                        ),
                        "ir_evidence": "B13: addi r34,r37,4; B1: addi r40,r37,4",
                        "catalog_ref": "subexpr-extract",
                    }
                ],
                "preflight": {
                    "safe": False,
                    "reasons": [
                        "no direct copy/identity edge between r34 and r40"
                    ],
                },
            }
        ],
    }


def _implicit_source_owner_payload() -> dict:
    return {
        "function": "mnDiagram_SortNamesByKOs",
        "mode": "discover",
        "register_class": "gpr",
        "pairs": [
            {
                "from": 35,
                "to": 42,
                "register_class": "gpr",
                "priority_class": "register-reuse",
                "ir_facts": {
                    "from": {
                        "virtual": 35,
                        "first_def": {
                            "block": 13,
                            "opcode": "mr",
                            "operands": "r35,r39",
                        },
                    },
                    "to": {
                        "virtual": 42,
                        "first_def": {
                            "block": 1,
                            "opcode": "mr",
                            "operands": "r42,r39",
                        },
                    },
                },
                "suggestions": [
                    {
                        "pattern": "common-subexpr",
                        "summary": (
                            "r35 and r42 are computed by identical IR ops "
                            "(mr r39)"
                        ),
                        "source_hint": (
                            "Hoist the shared expression into a temporary"
                        ),
                    }
                ],
                "preflight": {
                    "safe": False,
                    "reasons": [
                        "no direct copy/identity edge between r35 and r42"
                    ],
                },
            }
        ],
    }


def test_common_subexpr_coalesce_materializes_shared_rhs_probe() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int i) {\n"
        "    u8* dst_iter;\n"
        "    u8* mirror_iter;\n"
        "    dst_iter = dst + i;\n"
        "    mirror_iter = dst + i;\n"
        "    use(dst_iter, mirror_iter);\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 29, 40: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_suggest_payload(),
    )

    assert len(report.probes) == 1
    probe = report.probes[0]
    assert probe.probe_id == "retained_gpr_common_subexpr_coalesce_source@0"
    assert probe.mutator_key == "steer_retained_gpr_common_subexpr_coalesce_source"
    assert "u8* common_subexpr_r34_r40_probe;" in probe.candidate_text
    assert "common_subexpr_r34_r40_probe = dst + i;" in probe.candidate_text
    assert "dst_iter = common_subexpr_r34_r40_probe;" in probe.candidate_text
    assert "mirror_iter = common_subexpr_r34_r40_probe;" in probe.candidate_text
    assert probe.candidate_text.index(
        "u8* common_subexpr_r34_r40_probe;"
    ) < probe.candidate_text.index(
        "common_subexpr_r34_r40_probe = dst + i;"
    )
    assert probe.payload["coalesce_pair"] == {"from": 34, "to": 40}
    assert probe.payload["attempted_targets"] == {"34": 29, "40": 25}
    assert probe.payload["source_hunks"][0]["replacement_text"].startswith(
        "    u8* common_subexpr_r34_r40_probe"
    )
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.materialized_count == 1
    assert diagnostics.matcher_diagnostics["accepted_anchor_count"] == 1


def test_common_subexpr_coalesce_reports_type_mismatch_terminal_blocker() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int i) {\n"
        "    u8* dst_iter;\n"
        "    int mirror_iter;\n"
        "    dst_iter = dst + i;\n"
        "    mirror_iter = dst + i;\n"
        "    use(dst_iter, mirror_iter);\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 29, 40: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_suggest_payload(),
    )

    assert report.probes == ()
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.no_probe_reason == "common-subexpr-bridge-type-mismatch"
    assert diagnostics.matcher_diagnostics["terminal_blocker"] == (
        "common-subexpr-bridge-type-mismatch"
    )


def test_common_subexpr_coalesce_falls_back_to_common_pointer_base_owner(
) -> None:
    payload = _suggest_payload()
    payload["pairs"][0]["ir_facts"]["from"]["first_def"] = {
        "block": 13,
        "opcode": "mr",
        "operands": "r34,r37",
    }
    payload["pairs"][0]["ir_facts"]["to"]["first_def"] = {
        "block": 1,
        "opcode": "mr",
        "operands": "r40,r37",
    }
    payload["pairs"][0]["ir_facts"]["to"]["bridge"] = {
        "var": "j",
        "line": 10,
        "confidence": "low-confidence",
    }
    payload["pairs"].append({
        "from": 37,
        "to": 34,
        "register_class": "gpr",
        "ir_facts": {
            "from": {
                "virtual": 37,
                "first_def": {
                    "block": 0,
                    "opcode": "mr",
                    "operands": "r37,r3",
                },
                "bridge": {
                    "var": "dst",
                    "line": 4,
                    "confidence": "low-confidence",
                },
            }
        },
        "suggestions": [],
    })
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* arg0, int limit) {\n"
        "    u8* dst_iter;\n"
        "    u8* dst = arg0;\n"
        "    int i;\n"
        "    int j;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < limit; i++, ll_probe_iter_0++) {\n"
        "            for (j = i + 1; j < limit; j++) {\n"
        "                use(ll_probe_iter_0);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 40: 25, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=payload,
        max_per_family=2,
    )

    assert len(report.probes) == 2
    shared_base = report.probes[0]
    assert shared_base.payload["source_owner_strategy"] == (
        "common-source-shared-base-temp"
    )
    assert "u8* common_source_r37_probe;" in shared_base.candidate_text
    assert "common_source_r37_probe = dst;" in shared_base.candidate_text
    assert "dst_iter = common_source_r37_probe;" in shared_base.candidate_text
    assert "u8* ll_probe_iter_0 = common_source_r37_probe;" in (
        shared_base.candidate_text
    )
    reuse_owner = report.probes[1]
    assert reuse_owner.payload["source_owner_strategy"] == (
        "common-source-reuse-existing-owner"
    )
    assert "dst_iter = dst;" in reuse_owner.candidate_text
    assert "for (i = 0; i < limit; i++, dst_iter++)" in (
        reuse_owner.candidate_text
    )
    assert "use(dst_iter);" in reuse_owner.candidate_text
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.materialized_count == 2
    matcher = diagnostics.matcher_diagnostics
    assert matcher["accepted_anchor_count"] == 2
    assert matcher["source_owner_fallback_count"] == 2


def test_common_subexpr_coalesce_falls_back_to_implicit_pointer_source_owner(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        u8* ll_probe_end_0 = dst + limit;\n"
        "        for (i = 0; i < limit; i++, ll_probe_iter_0++) {\n"
        "            for (j = i + 1; j < limit; j++) {\n"
        "                use(ll_probe_iter_0, max_idx);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_implicit_source_owner_payload(),
        max_per_family=2,
    )

    assert len(report.probes) == 2
    shared_base = report.probes[0]
    assert shared_base.payload["source_owner_strategy"] == (
        "common-source-shared-base-temp"
    )
    assert shared_base.payload["source_owner_origin"] == (
        "implicit-repeated-pointer-rhs"
    )
    assert shared_base.payload["common_source_bridge"] is None
    assert shared_base.payload["common_source_var"] == "dst"
    assert shared_base.payload["protected_targets"] == {"34": 27, "44": 25}
    assert shared_base.payload["attempted_targets"] == {}
    assert "u8* common_source_r39_probe;" in shared_base.candidate_text
    assert "common_source_r39_probe = dst;" in shared_base.candidate_text
    assert "dst_iter = common_source_r39_probe;" in shared_base.candidate_text
    assert "u8* ll_probe_iter_0 = common_source_r39_probe;" in (
        shared_base.candidate_text
    )
    reuse_owner = report.probes[1]
    assert reuse_owner.payload["source_owner_strategy"] == (
        "common-source-reuse-existing-owner"
    )
    assert reuse_owner.payload["source_owner_origin"] == (
        "implicit-repeated-pointer-rhs"
    )
    assert "u8* ll_probe_iter_0 = dst;" not in reuse_owner.candidate_text
    assert (
        "        u8* ll_probe_end_0 = dst + limit;\n"
        "        dst_iter = dst;\n"
        in reuse_owner.candidate_text
    )
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.materialized_count == 2
    matcher = diagnostics.matcher_diagnostics
    assert matcher["accepted_anchor_count"] == 2
    assert matcher["source_owner_fallback_count"] == 2
    assert matcher["implicit_source_owner_fallback_count"] == 2
    assert matcher["pair_diagnostics"][0]["terminal_blocker"] is None


def test_common_subexpr_coalesce_shared_base_temp_is_c89_safe_after_pad_stack(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "#define PAD_STACK(x) do { use_stack(x); } while (0)\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    PAD_STACK(12);\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        use(ll_probe_iter_0);\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_implicit_source_owner_payload(),
        max_per_family=1,
    )

    assert len(report.probes) == 1
    candidate = report.probes[0].candidate_text
    assert "u8* common_source_r39_probe = dst;" not in candidate
    assert candidate.index("u8* common_source_r39_probe;") < candidate.index(
        "PAD_STACK(12);"
    )
    assert candidate.index("PAD_STACK(12);") < candidate.index(
        "common_source_r39_probe = dst;"
    )


def test_common_subexpr_coalesce_reuse_owner_skips_dependent_declarations(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        u8* ll_probe_end_0 = ll_probe_iter_0 + limit;\n"
        "        for (i = 0; i < limit; i++, ll_probe_iter_0++) {\n"
        "            for (j = i + 1; j < limit; j++) {\n"
        "                use(ll_probe_iter_0, ll_probe_end_0, max_idx);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_implicit_source_owner_payload(),
        max_per_family=2,
    )

    assert len(report.probes) == 1
    assert report.probes[0].payload["source_owner_strategy"] == (
        "common-source-shared-base-temp"
    )
    assert "u8* ll_probe_end_0 = dst_iter + limit;" not in (
        report.probes[0].candidate_text
    )
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.materialized_count == 1


def test_common_subexpr_coalesce_reports_missing_implicit_pointer_source_owner(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_implicit_source_owner_payload(),
    )

    assert report.probes == ()
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.no_probe_reason == (
        "common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs"
    )
    matcher = diagnostics.matcher_diagnostics
    assert matcher["terminal_blocker"] == (
        "common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs"
    )
    assert matcher["pair_diagnostics"][0]["terminal_blocker"] == (
        "common-subexpr-no-source-bridge-and-no-repeated-pointer-rhs"
    )


def test_common_subexpr_coalesce_reports_implicit_pointer_source_owner_type_mismatch(
) -> None:
    source = (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int ll_probe_iter_0;\n"
        "    int i;\n"
        "    dst_iter = dst;\n"
        "    ll_probe_iter_0 = dst;\n"
        "    for (i = 0; i < limit; i++) {\n"
        "        use(dst_iter, ll_probe_iter_0);\n"
        "    }\n"
        "}\n"
    )

    report = generate_transform_probe_report(
        source,
        function="mnDiagram_SortNamesByKOs",
        unit="melee/mn/mndiagram",
        force_phys={34: 27, 44: 25},
        force_class_id=0,
        families=[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID],
        coalesce_suggestion=_implicit_source_owner_payload(),
    )

    assert report.probes == ()
    diagnostics = {
        row.family_id: row for row in report.family_diagnostics
    }[RETAINED_GPR_COMMON_SUBEXPR_COALESCE_SOURCE_FAMILY_ID]
    assert diagnostics.no_probe_reason == (
        "common-subexpr-repeated-rhs-type-mismatch"
    )
    matcher = diagnostics.matcher_diagnostics
    assert matcher["terminal_blocker"] == (
        "common-subexpr-repeated-rhs-type-mismatch"
    )
    assert matcher["pair_diagnostics"][0]["terminal_blocker"] == (
        "common-subexpr-repeated-rhs-type-mismatch"
    )
