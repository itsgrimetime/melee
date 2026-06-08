from __future__ import annotations

import json
from pathlib import Path

import src.search.structure as structure_mod
from src.search.structure import (
    AxisSummary,
    StructureScoreResult,
    StructureVariant,
    generate_case_order_variants,
    generate_inline_boundary_variants,
    generate_loop_shape_expanded_variants,
    generate_statement_order_variants,
    normalize_control_flow_payload,
    normalize_decl_order_payload,
    rank_structure_variants,
    run_structure_search,
    structure_payload,
)


def test_rank_structure_variants_prefers_exact_then_match_then_delta() -> None:
    variants = [
        StructureVariant(
            axis="decl-order",
            operator="decl-order-swap",
            label="decl-micro",
            status="ok",
            baseline_percent=90.0,
            match_percent=91.0,
            final_match_percent=91.0,
            delta=1.0,
        ),
        StructureVariant(
            axis="case-order",
            operator="case-order-adjacent-swap",
            label="case-win",
            status="ok",
            baseline_percent=90.0,
            match_percent=100.0,
            final_match_percent=100.0,
            delta=10.0,
        ),
        StructureVariant(
            axis="control-flow",
            operator="ternary-to-if-else",
            label="cf-better",
            status="ok",
            baseline_percent=90.0,
            match_percent=99.0,
            final_match_percent=99.0,
            delta=9.0,
        ),
    ]

    ranked = rank_structure_variants(variants)

    assert [row.label for row in ranked] == ["case-win", "cf-better", "decl-micro"]
    assert [row.rank for row in ranked] == [1, 2, 3]


def test_source_lifetime_ranking_prefers_shape_preserved_candidate() -> None:
    ranked = rank_structure_variants([
        StructureVariant(
            axis="source-lifetime",
            operator="helper-result-dematerialize",
            label="shape-break",
            status="ok",
            final_match_percent=99.0,
            delta=1.0,
            metadata={"structural": {"opcode_shape_preserved": False}},
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="repeated-helper-result-reuse",
            label="shape-preserved",
            status="ok",
            final_match_percent=98.0,
            delta=0.5,
            metadata={"structural": {"opcode_shape_preserved": True}},
        ),
    ])

    assert [variant.label for variant in ranked] == ["shape-preserved", "shape-break"]


def test_source_lifetime_ranking_keeps_unscored_behind_ok_missing_structural() -> None:
    ranked = rank_structure_variants([
        StructureVariant(
            axis="source-lifetime",
            operator="helper-result-dematerialize",
            label="unscored-high-percent",
            status="unscored",
            final_match_percent=99.0,
            delta=9.0,
            compile_status="not-run",
            unscored_reason="scoring disabled",
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="repeated-helper-result-reuse",
            label="ok-missing-structural",
            status="ok",
            final_match_percent=90.0,
            delta=1.0,
            compile_status="ok",
        ),
    ])

    assert [variant.label for variant in ranked] == [
        "ok-missing-structural",
        "unscored-high-percent",
    ]


def test_source_lifetime_shape_ranking_does_not_affect_other_axes() -> None:
    ranked = rank_structure_variants([
        StructureVariant(
            axis="decl-order",
            operator="decl-order-swap",
            label="unrelated-low-unscored",
            status="unscored",
            final_match_percent=10.0,
            delta=-80.0,
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="helper-result-dematerialize",
            label="source-lifetime-high-shape-break",
            status="ok",
            final_match_percent=99.0,
            delta=9.0,
            compile_status="ok",
            metadata={"structural": {"opcode_shape_preserved": False}},
        ),
        StructureVariant(
            axis="case-order",
            operator="case-order-adjacent-swap",
            label="unrelated-higher-percent",
            status="ok",
            final_match_percent=99.5,
            delta=9.5,
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="repeated-helper-result-reuse",
            label="source-lifetime-shape-preserved",
            status="ok",
            final_match_percent=98.0,
            delta=8.0,
            compile_status="ok",
            metadata={"structural": {"opcode_shape_preserved": True}},
        ),
    ])

    assert [variant.label for variant in ranked] == [
        "unrelated-higher-percent",
        "source-lifetime-shape-preserved",
        "source-lifetime-high-shape-break",
        "unrelated-low-unscored",
    ]


def test_source_lifetime_ordering_spans_interleaved_other_axes_for_status() -> None:
    ranked = rank_structure_variants([
        StructureVariant(
            axis="source-lifetime",
            operator="helper-result-dematerialize",
            label="source-lifetime-unscored-high",
            status="unscored",
            final_match_percent=99.0,
            delta=9.0,
            compile_status="not-run",
            unscored_reason="scoring disabled",
        ),
        StructureVariant(
            axis="decl-order",
            operator="decl-order-swap",
            label="decl-order-middle",
            status="ok",
            final_match_percent=95.0,
            delta=5.0,
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="repeated-helper-result-reuse",
            label="source-lifetime-ok-missing-structural",
            status="ok",
            final_match_percent=90.0,
            delta=1.0,
            compile_status="ok",
        ),
    ])

    source_lifetime_labels = [
        variant.label for variant in ranked if variant.axis == "source-lifetime"
    ]
    assert source_lifetime_labels == [
        "source-lifetime-ok-missing-structural",
        "source-lifetime-unscored-high",
    ]
    assert [variant.label for variant in ranked] == [
        "source-lifetime-ok-missing-structural",
        "decl-order-middle",
        "source-lifetime-unscored-high",
    ]


def test_source_lifetime_ordering_spans_interleaved_other_axes_for_shape() -> None:
    ranked = rank_structure_variants([
        StructureVariant(
            axis="source-lifetime",
            operator="helper-result-dematerialize",
            label="source-lifetime-shape-break",
            status="ok",
            final_match_percent=99.0,
            delta=9.0,
            compile_status="ok",
            metadata={"structural": {"opcode_shape_preserved": False}},
        ),
        StructureVariant(
            axis="case-order",
            operator="case-order-adjacent-swap",
            label="case-order-middle",
            status="ok",
            final_match_percent=98.5,
            delta=8.5,
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="repeated-helper-result-reuse",
            label="source-lifetime-shape-preserved",
            status="ok",
            final_match_percent=98.0,
            delta=8.0,
            compile_status="ok",
            metadata={"structural": {"opcode_shape_preserved": True}},
        ),
    ])

    source_lifetime_labels = [
        variant.label for variant in ranked if variant.axis == "source-lifetime"
    ]
    assert source_lifetime_labels == [
        "source-lifetime-shape-preserved",
        "source-lifetime-shape-break",
    ]
    assert [variant.label for variant in ranked] == [
        "source-lifetime-shape-preserved",
        "case-order-middle",
        "source-lifetime-shape-break",
    ]


def test_normalize_control_flow_payload_preserves_retained_sources() -> None:
    payload = {
        "function": "fn_80000000",
        "variants": [
            {
                "label": "control-flow-ternary-0",
                "operator": "ternary-to-if-else",
                "status": "ok",
                "path": "/tmp/cf.c",
                "source_retained": "/tmp/cf.c",
                "match_percent": 98.0,
                "final_match_percent": 98.0,
                "match_percent_error": "partial report refresh",
                "probe": {"provenance": {"kind": "control-flow-shape"}},
            }
        ],
    }

    axis, variants = normalize_control_flow_payload(
        payload,
        baseline_percent=95.0,
        command="melee-agent debug mutate control-flow-shape-search -f fn_80000000 --json",
    )

    assert axis.axis == "control-flow"
    assert axis.status == "evaluated"
    assert axis.candidate_count == 1
    assert variants[0].delta == 3.0
    assert variants[0].source_retained == "/tmp/cf.c"
    assert variants[0].metadata["match_percent_error"] == "partial report refresh"
    assert variants[0].metadata["probe"]["provenance"]["kind"] == "control-flow-shape"


def test_normalize_decl_order_payload_emits_rerun_command_without_source() -> None:
    payload = {
        "function": "fn_80000000",
        "baseline_pct": 90.0,
        "best_pct": 91.25,
        "results": [
            {
                "label": "swap a <-> b",
                "strategy": "swap",
                "match_pct": 91.25,
                "delta": 1.25,
                "skipped": False,
            }
        ],
        "rounds": [
            {
                "results": [
                    {
                        "label": "promote skipped",
                        "strategy": "promote",
                        "match_pct": 92.0,
                        "delta": 2.0,
                        "skipped": True,
                    },
                    {
                        "label": "demote c",
                        "strategy": "demote",
                        "match_pct": 90.5,
                        "skipped": False,
                    },
                ],
            }
        ],
    }

    axis, variants = normalize_decl_order_payload(
        payload,
        baseline_percent=90.0,
        command=(
            "melee-agent debug mutate decl-orders fn_80000000 "
            "--strategy all --keep-best --json"
        ),
    )

    assert axis.axis == "decl-order"
    assert axis.status == "evaluated"
    assert axis.candidate_count == 2
    assert variants[0].operator == "decl-order-swap"
    assert variants[0].source_retained is None
    assert "--keep-best" not in variants[0].command
    assert "debug mutate decl-orders fn_80000000" in variants[0].command
    assert [variant.label for variant in variants] == ["swap a <-> b", "demote c"]
    assert variants[1].operator == "decl-order-demote"
    assert variants[1].delta == 0.5


def test_structure_payload_reports_future_axes_and_stop_condition() -> None:
    axis = AxisSummary(axis="case-order", status="blocked", blocker="no-case-order-probes")
    payload = structure_payload(
        function="fn_80000000",
        source="src/melee/demo.c",
        generated_source_dir="/tmp/structure",
        baseline_percent=80.0,
        axes=[axis],
        variants=[],
    )

    assert payload["stop_condition"]["kind"] == "no-improvement"
    assert payload["axes"][0]["blocker"] == "no-case-order-probes"
    assert payload["future_axes"] == []
    json.dumps(payload)

    exact_payload = structure_payload(
        function="fn_80000000",
        source="src/melee/demo.c",
        generated_source_dir="/tmp/structure",
        baseline_percent=80.0,
        axes=[],
        variants=[
            StructureVariant(
                axis="control-flow",
                operator="ternary-to-if-else",
                label="exact",
                status="ok",
                final_match_percent=100.0,
                delta=20.0,
            )
        ],
    )

    assert exact_payload["stop_condition"]["kind"] == "improved"

    candidate_payload = structure_payload(
        function="fn_80000000",
        source="src/melee/demo.c",
        generated_source_dir="/tmp/structure",
        baseline_percent=80.0,
        axes=[],
        variants=[
            StructureVariant(
                axis="case-order",
                operator="case-order-adjacent-swap",
                label="non-improving",
                status="ok",
                baseline_percent=80.0,
                match_percent=79.0,
                final_match_percent=79.0,
                delta=-1.0,
            ),
            StructureVariant(
                axis="statement-order",
                operator="statement-order-split-shift-or",
                label="unscored",
                status="unscored",
                unscored_reason="scoring disabled",
            ),
        ],
    )

    assert candidate_payload["stop_condition"]["kind"] == "candidates-generated"


def test_structure_payload_treats_compile_failed_candidates_as_verified() -> None:
    payload = structure_payload(
        function="fn_80000000",
        source="src/melee/demo.c",
        generated_source_dir="/tmp/structure",
        baseline_percent=80.0,
        axes=[],
        variants=[
            StructureVariant(
                axis="source-lifetime",
                operator="temp-introduction",
                label="compile-failed",
                status="unscored",
                compile_status="failed",
                unscored_reason="candidate compile failed: syntax error",
            )
        ],
    )

    assert payload["stop_condition"]["kind"] == "no-improvement"


def test_structure_payload_keeps_baseline_failures_unverified() -> None:
    for compile_status, reason in (
        ("failed", "baseline compile failed: compiler unavailable"),
        ("report-failed", "baseline report failed: report unavailable"),
        ("report-failed", "candidate report failed: report unavailable"),
    ):
        payload = structure_payload(
            function="fn_80000000",
            source="src/melee/demo.c",
            generated_source_dir="/tmp/structure",
            baseline_percent=None,
            axes=[],
            variants=[
                StructureVariant(
                    axis="source-lifetime",
                    operator="temp-introduction",
                    label="verification-failed",
                    status="unscored",
                    compile_status=compile_status,
                    unscored_reason=reason,
                )
            ],
        )

        assert payload["stop_condition"]["kind"] == "candidates-generated"


def test_run_structure_search_applies_fake_scores_and_ranks_variants(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "int fn_80000000(void)\n"
        "{\n"
        "    int first;\n"
        "    int second;\n"
        "    return 0;\n"
        "}\n"
    )

    def fake_score_runner(
        variants: list[StructureVariant],
    ) -> list[StructureScoreResult]:
        assert len(variants) >= 2
        return [
            StructureScoreResult(
                label=variants[0].label,
                baseline_percent=90.0,
                candidate_percent=88.0,
                compile_status="failed",
                unscored_reason="candidate compile failed: syntax error",
            ),
            StructureScoreResult(
                label=variants[1].label,
                baseline_percent=90.0,
                candidate_percent=92.5,
                compile_status="ok",
                structural={
                    "opcode_similarity": 0.97,
                    "line_delta": 0,
                    "hunk_count": 4,
                    "opcode_similarity_delta": 0.02,
                },
            ),
        ]

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("decl-order",),
        max_candidates=6,
        score_variants=True,
        score_runner=fake_score_runner,
    )

    assert payload["stop_condition"]["kind"] == "improved"
    assert [row["status"] for row in payload["variants"][:2]] == ["ok", "unscored"]
    assert payload["variants"][0]["compile_status"] == "ok"
    assert payload["variants"][0]["baseline_percent"] == 90.0
    assert payload["variants"][0]["match_percent"] == 92.5
    assert payload["variants"][0]["final_match_percent"] == 92.5
    assert payload["variants"][0]["delta"] == 2.5
    assert payload["variants"][0]["metadata"]["structural"]["hunk_count"] == 4
    assert payload["variants"][1]["compile_status"] == "failed"
    assert payload["variants"][1]["unscored_reason"] == (
        "candidate compile failed: syntax error"
    )


def test_run_structure_search_keeps_score_when_checkdiff_metadata_fails(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "int fn_80000000(void)\n"
        "{\n"
        "    int first;\n"
        "    int second;\n"
        "    return 0;\n"
        "}\n"
    )

    def fake_score_runner(
        variants: list[StructureVariant],
    ) -> list[StructureScoreResult]:
        return [
            StructureScoreResult(
                label=variants[0].label,
                baseline_percent=90.0,
                candidate_percent=91.25,
                compile_status="ok",
                checkdiff_status="failed",
                unscored_reason="candidate checkdiff failed: non-json",
            )
        ]

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("decl-order",),
        max_candidates=1,
        score_variants=True,
        score_runner=fake_score_runner,
    )

    variant = payload["variants"][0]
    assert variant["status"] == "unscored"
    assert variant["compile_status"] == "ok"
    assert variant["checkdiff_status"] == "failed"
    assert variant["baseline_percent"] == 90.0
    assert variant["match_percent"] == 91.25
    assert variant["final_match_percent"] == 91.25
    assert variant["delta"] == 1.25
    assert variant["unscored_reason"] == "candidate checkdiff failed: non-json"
    assert payload["stop_condition"]["kind"] == "improved"


def test_run_structure_search_scores_no_more_than_max_candidates(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "int fn_80000000(int mode)\n"
        "{\n"
        "    int first;\n"
        "    int second;\n"
        "    int third;\n"
        "    switch (mode) {\n"
        "    case 0:\n"
        "        return first;\n"
        "    case 1:\n"
        "        return second;\n"
        "    }\n"
        "    return third;\n"
        "}\n"
    )
    scored_counts: list[int] = []
    scored_labels: list[str] = []

    def fake_score_runner(
        variants: list[StructureVariant],
    ) -> list[StructureScoreResult]:
        scored_counts.append(len(variants))
        scored_labels.extend(variant.label for variant in variants)
        return [
            StructureScoreResult(
                label=variant.label,
                baseline_percent=90.0,
                candidate_percent=None,
                compile_status="failed",
                unscored_reason="candidate compile failed: syntax error",
            )
            for variant in variants
        ]

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("decl-order", "case-order"),
        max_candidates=1,
        score_variants=True,
        score_runner=fake_score_runner,
    )

    assert scored_counts == [1]
    assert len(payload["variants"]) == 1
    assert payload["variants"][0]["label"] == scored_labels[0]
    assert payload["variants"][0]["compile_status"] == "failed"
    assert payload["variants"][0]["unscored_reason"] == (
        "candidate compile failed: syntax error"
    )
    assert payload["stop_condition"]["kind"] == "candidates-generated"


def test_run_structure_search_marks_generated_candidates_unscored_without_runner(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "int fn_80000000(void)\n"
        "{\n"
        "    int first;\n"
        "    int second;\n"
        "    return 0;\n"
        "}\n"
    )

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("decl-order",),
        max_candidates=2,
    )

    assert payload["variants"]
    assert {row["status"] for row in payload["variants"]} == {"unscored"}
    assert {row["unscored_reason"] for row in payload["variants"]} == {
        "scoring disabled"
    }
    assert payload["stop_condition"]["kind"] == "candidates-generated"


def test_structure_payload_reports_no_improvement_when_all_candidates_scored() -> None:
    payload = structure_payload(
        function="fn_80000000",
        source="src/melee/demo.c",
        generated_source_dir="/tmp/structure",
        baseline_percent=80.0,
        axes=[],
        variants=[
            StructureVariant(
                axis="case-order",
                operator="case-order-adjacent-swap",
                label="worse",
                status="ok",
                baseline_percent=80.0,
                match_percent=79.0,
                final_match_percent=79.0,
                delta=-1.0,
                compile_status="ok",
            )
        ],
    )

    assert payload["stop_condition"]["kind"] == "no-improvement"


def test_run_structure_search_generates_candidates_without_live_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    original = (
        "int fn_80000000(int mode)\n"
        "{\n"
        "    int first;\n"
        "    int second;\n"
        "    switch (mode) {\n"
        "    case 0:\n"
        "        first = 1;\n"
        "        break;\n"
        "    case 1:\n"
        "        second = 2;\n"
        "        break;\n"
        "    }\n"
        "    return first + second;\n"
        "}\n"
    )
    source_path.write_text(original)

    def fail_subprocess_run(*args, **kwargs):
        raise AssertionError(
            "structure search default path must not mutate via subprocess axes"
        )

    monkeypatch.setattr(structure_mod.subprocess, "run", fail_subprocess_run)

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("decl-order", "control-flow", "case-order"),
        max_candidates=6,
    )

    assert source_path.read_text() == original
    axes = {axis["axis"]: axis for axis in payload["axes"]}
    assert axes["decl-order"]["status"] == "evaluated"
    assert axes["decl-order"]["candidate_count"] > 0
    assert "control-flow" in axes
    assert axes["case-order"]["status"] == "evaluated"
    retained = [
        Path(variant["source_retained"])
        for variant in payload["variants"]
        if variant["axis"] == "decl-order"
    ]
    assert retained
    assert all(path.exists() for path in retained)
    assert all(str(path).startswith(str(tmp_path / "structure")) for path in retained)


def _statement_source(body: str) -> str:
    return (
        "int fn_80000000(int seed, unsigned char* p)\n"
        "{\n"
        f"{body}"
        "}\n"
    )


def test_statement_order_generates_split_and_fuse_shift_or_candidates(
    tmp_path: Path,
) -> None:
    source = _statement_source(
        "    unsigned int size;\n"
        "    size = (size << 8) | p[3];\n"
        "    size <<= 8;\n"
        "    size |= p[4];\n"
        "    return size;\n"
    )

    axis, variants = generate_statement_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=82.84,
        max_candidates=8,
    )

    assert axis.axis == "statement-order"
    assert axis.status == "evaluated"
    assert {variant.operator for variant in variants} >= {
        "statement-order-split-shift-or",
        "statement-order-fuse-shift-or",
    }
    split = next(
        variant
        for variant in variants
        if variant.operator == "statement-order-split-shift-or"
    )
    split_text = Path(split.source_retained).read_text()
    assert "size <<= 8;" in split_text
    assert "size |= p[3];" in split_text
    assert split.metadata["lhs"] == "size"
    assert split.metadata["touched_lines"] == {"start": 4, "end": 4}
    assert "-    size = (size << 8) | p[3];" in split.metadata["source_diff"]
    assert "+    size <<= 8;" in split.metadata["source_diff"]

    fuse = next(
        variant
        for variant in variants
        if variant.operator == "statement-order-fuse-shift-or"
    )
    fuse_text = Path(fuse.source_retained).read_text()
    assert "size = (size << 8) | p[4];" in fuse_text


def test_statement_order_rejects_unsafe_shift_or_sources(tmp_path: Path) -> None:
    unsafe_bodies = [
        "    unsigned int size;\n"
        "    /* size = (size << 8) | p[3]; */\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    const char* s = \"size = (size << 8) | p[3];\";\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "#if 1\n"
        "    size = (size << 8) | p[3];\n"
        "#endif\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | size;\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | (seed = p[3]);\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | (seed >>= 1);\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | p[seed++];\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | p[seed--];\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | (p[3], p[4]);\n"
        "    return size;\n",
        "    unsigned int size;\n"
        "    size = (size << 8) | (seed ? p[3] : p[4]);\n"
        "    return size;\n",
    ]

    for body in unsafe_bodies:
        axis, variants = generate_statement_order_variants(
            _statement_source(body),
            "fn_80000000",
            output_dir=tmp_path,
            baseline_percent=82.84,
        )
        assert [
            variant
            for variant in variants
            if variant.operator == "statement-order-split-shift-or"
        ] == []
        if "#if" in body:
            assert axis.blocker == "unsafe-statement-order-preprocessor"


def test_statement_order_rejects_fuse_when_comments_separate_statements(
    tmp_path: Path,
) -> None:
    source = _statement_source(
        "    unsigned int size;\n"
        "    size <<= 8;\n"
        "    /* retained note */\n"
        "    size |= p[3];\n"
        "    return size;\n"
    )

    _axis, variants = generate_statement_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=82.84,
    )

    assert [
        variant
        for variant in variants
        if variant.operator == "statement-order-fuse-shift-or"
    ] == []


def test_statement_order_generates_only_safe_local_scalar_swaps(tmp_path: Path) -> None:
    source = _statement_source(
        "    int a;\n"
        "    int b;\n"
        "    int c;\n"
        "    a = seed;\n"
        "    b = seed + 1;\n"
        "    c = a + b;\n"
        "    return c;\n"
    )

    axis, variants = generate_statement_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=82.84,
        max_candidates=8,
    )

    swaps = [
        variant
        for variant in variants
        if variant.operator == "statement-order-adjacent-swap"
    ]
    assert axis.status == "evaluated"
    assert len(swaps) == 1
    assert swaps[0].metadata["statement_order"] == [
        "b = seed + 1;",
        "a = seed;",
    ]
    swap_text = Path(swaps[0].source_retained).read_text()
    assert swap_text.index("b = seed + 1;") < swap_text.index("a = seed;")
    assert "c = a + b;" in swap_text

    unknown_source = _statement_source(
        "    int a;\n"
        "    int b;\n"
        "    a = global_value;\n"
        "    b = seed;\n"
        "    return a + b;\n"
    )
    _axis, unsafe_variants = generate_statement_order_variants(
        unknown_source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=82.84,
    )
    assert [
        variant
        for variant in unsafe_variants
        if variant.operator == "statement-order-adjacent-swap"
    ] == []

    nested_decl_source = _statement_source(
        "    int a;\n"
        "    int b;\n"
        "    if (seed) {\n"
        "        int global_value;\n"
        "    }\n"
        "    a = global_value;\n"
        "    b = seed;\n"
        "    return a + b;\n"
    )
    _axis, nested_decl_variants = generate_statement_order_variants(
        nested_decl_source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=82.84,
    )
    assert [
        variant
        for variant in nested_decl_variants
        if variant.operator == "statement-order-adjacent-swap"
    ] == []

    leading_comment_decl_source = _statement_source(
        "    /*\n"
        "    int global_value;\n"
        "    */ int a;\n"
        "    int b;\n"
        "    global_value = seed;\n"
        "    b = seed;\n"
        "    return b;\n"
    )
    _axis, leading_comment_variants = generate_statement_order_variants(
        leading_comment_decl_source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=82.84,
    )
    assert [
        variant
        for variant in leading_comment_variants
        if variant.operator == "statement-order-adjacent-swap"
    ] == []


def test_run_structure_search_supports_statement_order_axis(tmp_path: Path) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        _statement_source(
            "    unsigned int size;\n"
            "    size = (size << 8) | p[3];\n"
            "    return size;\n"
        )
    )

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("statement-order",),
        max_candidates=4,
    )

    axes = {axis["axis"]: axis for axis in payload["axes"]}
    assert axes["statement-order"]["status"] == "evaluated"
    assert payload["variants"][0]["axis"] == "statement-order"
    assert Path(payload["variants"][0]["source_retained"]).exists()
    assert "statement-order" not in {row["axis"] for row in payload["future_axes"]}
    assert payload["stop_condition"]["kind"] == "candidates-generated"


def test_run_structure_search_source_lifetime_axis_emits_retained_candidates(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "s32 fn_803AC7DC(CardState* state, s32 i)\n"
        "{\n"
        "    s32 total = 0;\n"
        "    total += fn_803AC634(state, i);\n"
        "    if (total < (s32) fn_803AC634(state, i)) {\n"
        "        total = (s32) fn_803AC634(state, i);\n"
        "    }\n"
        "    return total;\n"
        "}\n"
    )

    payload = run_structure_search(
        "fn_803AC7DC",
        source_path,
        tmp_path / "structure",
        axes=("source-lifetime",),
        max_candidates=2,
        score_variants=False,
    )

    assert payload["axes"][0]["axis"] == "source-lifetime"
    assert payload["axes"][0]["status"] == "evaluated"
    assert payload["axes"][0]["metadata"]["families"]
    assert payload["variants"]
    assert all(row["axis"] == "source-lifetime" for row in payload["variants"])
    assert all(Path(row["source_retained"]).exists() for row in payload["variants"])


def test_source_lifetime_axis_prioritizes_targeted_probes_under_small_cap(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "s32 fn_803ACD58(CardState* state)\n"
        "{\n"
        "    s32 i;\n"
        "    s32 size;\n"
        "    s32 total;\n"
        "    for (i = 0; size = state->x8, i < (0x2F + state->x24 + size) / size; i++) {\n"
        "        total += i;\n"
        "    }\n"
        "    return total;\n"
        "}\n"
    )

    payload = run_structure_search(
        "fn_803ACD58",
        source_path,
        tmp_path / "structure",
        axes=("source-lifetime",),
        max_candidates=1,
        score_variants=False,
    )

    assert payload["variants"][0]["operator"] == "for-condition-field-reload"


def test_source_lifetime_axis_retains_cleanup_loop_role_shape_under_small_cap(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "void fn_80000000(Diagram3* data)\n"
        "{\n"
        "    int i;\n"
        "    for (i = 0; i < 0xA; i++) {\n"
        "        if (data->row_labels[i] != NULL) {\n"
        "            HSD_SisLib_803A5CC4(data->row_labels[i]);\n"
        "            data->row_labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "    for (i = 0; i < 0xA; i++) {\n"
        "        if (data->column_labels[i] != NULL) {\n"
        "            HSD_SisLib_803A5CC4(data->column_labels[i]);\n"
        "            data->column_labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("source-lifetime",),
        max_candidates=3,
        score_variants=False,
    )

    assert [row["axis"] for row in payload["variants"][:3]] == [
        "source-lifetime",
        "source-lifetime",
        "source-lifetime",
    ]
    cleanup_labels = [
        row["label"]
        for row in payload["variants"]
        if row["operator"] == "cleanup-loop-role-shape"
    ]
    assert cleanup_labels
    assert cleanup_labels[0].startswith("cleanup-loop-all-")
    assert all(Path(row["source_retained"]).exists() for row in payload["variants"])


def test_inline_boundary_wraps_late_fake_axis_setter_with_prototype(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    HSD_JObjSetTranslateY(jobj, y);\n"
        "}\n"
        "\n"
        "static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    jobj->translate.y = y;\n"
        "}\n"
    )

    axis, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=42.0,
        max_candidates=4,
    )

    assert axis.status == "evaluated"
    wrapper = next(
        row for row in variants if row.operator == "inline-boundary-axis-setter-wrapper"
    )
    retained = Path(wrapper.source_retained or "")
    retained_text = retained.read_text()
    prototype = (
        "static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y);"
    )
    assert retained_text.index(prototype) < retained_text.index(
        "void fn_80000000"
    )
    assert "HSD_JObjSetTranslateY_Fake(jobj, y);" in retained_text


def test_inline_boundary_generates_user_data_and_cleanup_helper_candidates(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(GObj* gobj)\n"
        "{\n"
        "    Diagram3* data;\n"
        "    int i;\n"
        "    data = gobj->user_data;\n"
        "    for (i = 0; i < 0xA; i++) {\n"
        "        if (data->row_labels[i] != NULL) {\n"
        "            HSD_SisLib_803A5CC4(data->row_labels[i]);\n"
        "            data->row_labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    axis, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    assert axis.status == "evaluated"
    by_operator = {row.operator: row for row in variants}
    cast = by_operator["inline-boundary-user-data-cast"]
    helper = by_operator["inline-boundary-sislib-cleanup-helper"]
    assert "(Diagram3*) gobj->user_data" in Path(
        cast.source_retained or ""
    ).read_text()
    helper_text = Path(helper.source_retained or "").read_text()
    assert helper_text.index("ll_probe_sislib_clear_text_0") < helper_text.index(
        "void fn_80000000"
    )
    assert "ll_probe_sislib_clear_text_0(&data->row_labels[i]);" in helper_text


def test_run_structure_search_supports_inline_boundary_axis(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "void fn_80000000(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    HSD_JObjSetTranslateY(jobj, y);\n"
        "}\n"
        "\n"
        "static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    jobj->translate.y = y;\n"
        "}\n"
    )

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("inline-boundary",),
        max_candidates=4,
        score_variants=False,
    )

    assert payload["axes"][0]["axis"] == "inline-boundary"
    assert payload["axes"][0]["status"] == "evaluated"
    assert payload["variants"][0]["axis"] == "inline-boundary"
    assert "inline-boundary" not in {row["axis"] for row in payload["future_axes"]}


def _loop_shape_source(body: str) -> str:
    return (
        "void fn_80000000(int arg1, int arg2, mnDiagram_Assets* assets)\n"
        "{\n"
        f"{body}"
        "}\n"
    )


def test_loop_shape_expanded_generates_clean_name_scan_families(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int i;\n"
        "    s32 idx;\n"
        "    s32 remaining;\n"
        "    u8 name_id;\n"
        "    u8* p;\n"
        "    u8* p2;\n"
        "    for (i = 0; i < 7; i++) {\n"
        "        idx = arg2;\n"
        "        remaining = i;\n"
        "        p = &assets->sorted_names[arg2];\n"
        "        while (remaining > 0) {\n"
        "            p2 = p;\n"
        "        col_inner:\n"
        "            idx++;\n"
        "            p2++;\n"
        "            p++;\n"
        "            if (idx >= 0x78) {\n"
        "                name_id = 0x78;\n"
        "                goto col_found;\n"
        "            }\n"
        "            if (GetNameText(*p2) == NULL) {\n"
        "                goto col_inner;\n"
        "            }\n"
        "            remaining--;\n"
        "        }\n"
        "        name_id = assets->sorted_names[idx];\n"
        "    col_found:\n"
        "        sink(GetNameText(name_id));\n"
        "    }\n"
    )

    axis, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=12,
    )

    assert axis.status == "evaluated"
    operators = {variant.operator for variant in variants}
    assert operators >= {
        "loop-shape-expanded-direct-index",
        "loop-shape-expanded-base-pointer",
        "loop-shape-expanded-predicate-temp",
        "loop-shape-expanded-inverted-predicate",
        "loop-shape-expanded-helper",
    }
    assert all(variant.metadata["live_mutation"] is False for variant in variants)
    assert all(Path(variant.source_retained or "").exists() for variant in variants)
    text = "\n".join(Path(variant.source_retained or "").read_text() for variant in variants)
    assert "assets->sorted_names" in text
    assert "GetNameText" in text
    helper = next(
        variant
        for variant in variants
        if variant.operator == "loop-shape-expanded-helper"
    )
    helper_text = Path(helper.source_retained or "").read_text()
    assert "static inline u8 lse_probe_visible_entry_0(" in helper_text
    assert "name_id = lse_probe_visible_entry_0(" in helper_text
    assert "GetNameText(base[idx]) != NULL" in helper_text
    assert len({Path(variant.source_retained or "").read_text() for variant in variants}) == len(variants)


def test_loop_shape_expanded_ignores_unrelated_sorted_refs_without_predicate_evidence(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int idx = arg2;\n"
        "    u8 name_id;\n"
        "    sink(GetNameText(7));\n"
        "    name_id = assets->sorted_names[idx];\n"
        "    sink(name_id);\n"
    )

    axis, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    assert variants == []
    assert axis.status == "blocked"
    assert axis.blocker == "no-loop-shape-expanded-candidates"


def test_loop_shape_expanded_rewrites_detected_row_occurrence_not_first_column(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int idx;\n"
        "    u8* p;\n"
        "    u8* p2;\n"
        "    idx = arg2;\n"
        "    p = &assets->sorted_names[arg2];\n"
        "    p2 = p;\n"
        "    sink(assets->sorted_names[arg2]);\n"
        "    idx = arg1;\n"
        "    p = &assets->sorted_names[arg1];\n"
        "    p2 = p;\n"
        "row_inner:\n"
        "    idx++;\n"
        "    p2++;\n"
        "    if (GetNameText(*p2) == NULL) {\n"
        "        goto row_inner;\n"
        "    }\n"
    )

    _, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=12,
    )

    base = next(
        variant
        for variant in variants
        if variant.operator == "loop-shape-expanded-base-pointer"
    )
    direct = next(
        variant
        for variant in variants
        if variant.operator == "loop-shape-expanded-direct-index"
    )
    base_text = Path(base.source_retained or "").read_text()
    direct_text = Path(direct.source_retained or "").read_text()
    assert "p = &assets->sorted_names[arg2];" in base_text
    assert "p = assets->sorted_names + arg1;" in base_text
    assert "GetNameText(assets->sorted_names[idx])" in direct_text
    assert "GetNameText(p2[0])" not in direct_text


def test_loop_shape_expanded_helper_replaces_scan_and_goto_heavy_skips_helper(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int i = 3;\n"
        "    int idx = arg2;\n"
        "    u8 name_id;\n"
        "    u8* p;\n"
        "    u8* p2;\n"
        "    p = &assets->sorted_names[arg2];\n"
        "    while (i > 0) {\n"
        "        p2 = p;\n"
        "    loop:\n"
        "        idx++;\n"
        "        p2++;\n"
        "        p++;\n"
        "        if (idx >= 0x78) {\n"
        "            name_id = 0x78;\n"
        "            goto found;\n"
        "        }\n"
        "        if (GetNameText(*p2) == NULL) {\n"
        "            goto loop;\n"
        "        }\n"
        "        i--;\n"
        "    }\n"
        "    name_id = assets->sorted_names[idx];\n"
        "found:\n"
        "    sink(name_id);\n"
    )

    _, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )
    helper = next(
        variant
        for variant in variants
        if variant.operator == "loop-shape-expanded-helper"
    )
    helper_text = Path(helper.source_retained or "").read_text()
    assert "static inline u8 lse_probe_visible_entry_0(u8* base, int idx, int remaining, int limit)" in helper_text
    assert "name_id = lse_probe_visible_entry_0(assets->sorted_names, arg2, i, 0x78);" in helper_text

    actual_source = Path("src/melee/mn/mndiagram.c").read_text()
    _, heavy_variants = generate_loop_shape_expanded_variants(
        actual_source,
        "mnDiagram_8024227C",
        tmp_path / "heavy",
        baseline_percent=None,
        max_candidates=40,
    )
    assert heavy_variants
    assert not any(
        variant.operator == "loop-shape-expanded-helper"
        for variant in heavy_variants
    )


def test_loop_shape_expanded_inverts_simple_goto_condition_to_else_goto(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int idx = arg2;\n"
        "loop:\n"
        "    idx++;\n"
        "    if (GetNameText(assets->sorted_names[idx]) == NULL) {\n"
        "        goto loop;\n"
        "    }\n"
    )

    _, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )
    inverted = next(
        variant
        for variant in variants
        if variant.operator == "loop-shape-expanded-inverted-predicate"
    )
    text = Path(inverted.source_retained or "").read_text()
    assert "if (GetNameText(assets->sorted_names[idx]) != NULL) {" in text
    assert "} else {\n        goto loop;\n    }" in text
    assert "!(" not in text


def test_loop_shape_expanded_small_cap_interleaves_families_for_scan(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int idx = arg2;\n"
        "    int k;\n"
        "    int remaining = 3;\n"
        "    u8 name_id;\n"
        "    u8* p;\n"
        "    u8* p2;\n"
        "    for (k = 0; k < 0x78; k++) {\n"
        "        if (GetNameText(k) != NULL) {\n"
        "            sink(k);\n"
        "        }\n"
        "    }\n"
        "    p = &assets->sorted_names[arg2];\n"
        "    while (remaining > 0) {\n"
        "        p2 = p;\n"
        "loop:\n"
        "    idx++;\n"
        "        p2++;\n"
        "        p++;\n"
        "        if (GetNameText(*p2) == NULL) {\n"
        "        goto loop;\n"
        "    }\n"
        "        remaining--;\n"
        "    }\n"
        "    name_id = assets->sorted_names[idx];\n"
        "    sink(name_id);\n"
    )

    _, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    operators = {variant.operator for variant in variants}
    assert len(variants) == 4
    assert operators >= {
        "loop-shape-expanded-direct-index",
        "loop-shape-expanded-predicate-temp",
        "loop-shape-expanded-inverted-predicate",
        "loop-shape-expanded-helper",
    }
    assert all(variant.metadata["scan"]["expr"] != "k" for variant in variants)


def test_loop_shape_expanded_direct_index_avoids_overlapping_final_load_rewrite(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int idx = arg2;\n"
        "    u8 name_id;\n"
        "loop:\n"
        "    idx++;\n"
        "    if (GetNameText(assets->sorted_names[idx]) == NULL) {\n"
        "        goto loop;\n"
        "    }\n"
        "    name_id = assets->sorted_names[idx];\n"
        "    sink(name_id);\n"
    )

    axis, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=12,
    )

    assert axis.metadata["scan_count"] >= 2
    direct_sources = [
        Path(variant.source_retained or "").read_text()
        for variant in variants
        if variant.operator == "loop-shape-expanded-direct-index"
    ]
    assert direct_sources
    assert all("];" not in text[text.find("name_id = *("):text.find("sink(name_id);")] for text in direct_sources)
    assert any(
        "name_id = *(assets->sorted_names + idx);" in text
        for text in direct_sources
    )


def test_loop_shape_expanded_keeps_repeated_scans_that_reuse_locals(
    tmp_path: Path,
) -> None:
    source = _loop_shape_source(
        "    int idx;\n"
        "    u8* p;\n"
        "    u8* p2;\n"
        "    idx = arg1;\n"
        "    p = &assets->sorted_names[arg1];\n"
        "    p2 = p;\n"
        "row_inner:\n"
        "    idx++;\n"
        "    p2++;\n"
        "    if (GetNameText(*p2) == NULL) {\n"
        "        goto row_inner;\n"
        "    }\n"
        "    idx = arg2;\n"
        "    p = &assets->sorted_names[arg2];\n"
        "    p2 = p;\n"
        "col_inner:\n"
        "    idx++;\n"
        "    p2++;\n"
        "    if (GetNameText(*p2) == NULL) {\n"
        "        goto col_inner;\n"
        "    }\n"
    )

    axis, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=20,
    )

    assert axis.metadata["scan_count"] >= 2
    direct_sources = [
        Path(variant.source_retained or "").read_text()
        for variant in variants
        if variant.operator == "loop-shape-expanded-base-pointer"
    ]
    assert any("p = assets->sorted_names + arg1;" in text for text in direct_sources)
    assert any("p = assets->sorted_names + arg2;" in text for text in direct_sources)


def test_loop_shape_expanded_detects_fighter_global_and_alias_sources(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int arg1, int arg2)\n"
        "{\n"
        "    int i;\n"
        "    int idx;\n"
        "    int remaining;\n"
        "    u8 fighter_id;\n"
        "    u8 name_id;\n"
        "    u8* sorted = mnDiagram_804A0750.sorted_fighters;\n"
        "    for (i = 0; i < 7; i++) {\n"
        "        idx = arg2;\n"
        "        remaining = i;\n"
        "        while (remaining >= 0) {\n"
        "            if (mn_IsFighterUnlocked(sorted[idx]) != 0) {\n"
        "                remaining--;\n"
        "            }\n"
        "            idx++;\n"
        "        }\n"
        "        fighter_id = mnDiagram_804A0750.sorted_fighters[idx];\n"
        "        name_id = *(sorted + 0x1C + idx);\n"
        "        sink(fighter_id, name_id);\n"
        "    }\n"
        "}\n"
    )

    axis, variants = generate_loop_shape_expanded_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=80.0,
        max_candidates=12,
    )

    assert axis.status == "evaluated"
    source_kinds = {
        variant.metadata["scan"]["source_kind"] for variant in variants
    }
    assert "mnDiagram_804A0750.sorted_fighters" in source_kinds
    assert "local-alias-sorted-fighters" in source_kinds
    assert "alias-offset-sorted-names" in source_kinds
    assert any(
        variant.metadata["scan"]["predicate"] == "mn_IsFighterUnlocked"
        for variant in variants
    )


def test_loop_shape_expanded_blocks_when_source_is_unsafe(
    tmp_path: Path,
) -> None:
    missing = run_structure_search(
        "fn_80000000",
        None,
        tmp_path / "missing-source",
        axes=("loop-shape-expanded",),
    )
    assert missing["axes"][0]["blocker"] == "source-unavailable"

    source_path = tmp_path / "demo.c"
    source_path.write_text("void other(void) {}\n")
    not_found = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "not-found",
        axes=("loop-shape-expanded",),
    )
    assert not_found["axes"][0]["blocker"] == "source-unavailable"

    source_path.write_text(
        "void fn_80000000(mnDiagram_Assets* assets, int idx)\n"
        "{\n"
        "#if 1\n"
        "    sink(assets->sorted_names[idx]);\n"
        "#endif\n"
        "}\n"
    )
    preprocessor = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "preprocessor",
        axes=("loop-shape-expanded",),
    )
    assert preprocessor["axes"][0]["blocker"] == "unsafe-loop-shape-preprocessor"


def test_run_structure_search_supports_loop_shape_expanded_axis(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        _loop_shape_source(
            "    int idx = arg2;\n"
            "    int remaining = 3;\n"
            "    u8 name_id;\n"
            "    while (remaining > 0) {\n"
            "        idx++;\n"
            "        if (idx >= 0x78) {\n"
            "            name_id = 0x78;\n"
            "            goto found;\n"
            "        }\n"
            "        if (GetNameText(assets->sorted_names[idx]) != NULL) {\n"
            "            remaining--;\n"
            "        }\n"
            "    }\n"
            "    name_id = assets->sorted_names[idx];\n"
            "found:\n"
            "    sink(name_id);\n"
        )
    )

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("loop-shape-expanded",),
        max_candidates=8,
        score_variants=False,
    )

    assert payload["axes"][0]["axis"] == "loop-shape-expanded"
    assert payload["axes"][0]["status"] == "evaluated"
    assert payload["variants"]
    assert all(row["axis"] == "loop-shape-expanded" for row in payload["variants"])
    assert all(row["metadata"]["live_mutation"] is False for row in payload["variants"])
    assert "loop-shape-expanded" not in {row["axis"] for row in payload["future_axes"]}


def test_loop_shape_expanded_covers_actual_mndiagram_visible_scans(
    tmp_path: Path,
) -> None:
    source_path = Path("src/melee/mn/mndiagram.c")
    source = source_path.read_text()
    expected = {
        "mnDiagram_802427B4": {"assets->sorted_names", "GetNameText"},
        "mnDiagram_80242C0C": {"assets->sorted_fighters", "mn_IsFighterUnlocked"},
        "mnDiagram_8024227C": {"assets->sorted_names", "assets->sorted_fighters"},
        "mnDiagram_802417D0": {"local-alias-sorted-fighters", "alias-offset-sorted-names"},
    }

    for function, required in expected.items():
        axis, variants = generate_loop_shape_expanded_variants(
            source,
            function,
            tmp_path / function,
            baseline_percent=None,
            max_candidates=32,
        )
        assert axis.status == "evaluated", function
        assert variants, function
        haystack = {
            variant.metadata["scan"].get("source_kind") for variant in variants
        } | {
            variant.metadata["scan"].get("predicate") for variant in variants
        }
        assert required <= haystack
        assert all(Path(variant.source_retained or "").exists() for variant in variants)

    variants_417d0 = generate_loop_shape_expanded_variants(
        source,
        "mnDiagram_802417D0",
        tmp_path / "mnDiagram_802417D0-snippets",
        baseline_percent=None,
        max_candidates=32,
    )[1]
    assert any(
        "sorted + 0x1C" in Path(variant.source_retained or "").read_text()
        for variant in variants_417d0
    )

    variants_4227c = generate_loop_shape_expanded_variants(
        source,
        "mnDiagram_8024227C",
        tmp_path / "mnDiagram_8024227C-snippets",
        baseline_percent=None,
        max_candidates=40,
    )[1]
    assert any(
        "loop_7" in Path(variant.source_retained or "").read_text()
        and "var_r17" in Path(variant.source_retained or "").read_text()
        for variant in variants_4227c
    )


def test_inline_boundary_axis_reports_shifted_missing_reference_metadata(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    sink(GetNameText(0));\n"
        "}\n"
    )
    classification = {
        "primary": "inline-boundary-toolchain-artifact",
        "inline_boundary_artifact": {
            "missing_ref_calls": [
                "<fn_80000000+0x10>",
                "<fn_80000000+0x24>",
            ],
        },
    }

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("inline-boundary",),
        max_candidates=4,
        score_variants=False,
        baseline_classification=classification,
    )

    metadata = payload["axes"][0]["metadata"]["inline_boundary_artifact"]
    assert metadata["missing_ref_call_count"] == 2
    assert metadata["same_function_offset_count"] == 2
    assert metadata["source_lever_classification"] == "shifted-same-target-calls"


def test_inline_boundary_generates_call_result_temp_for_if_condition(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int j)\n"
        "{\n"
        "    if (GetNameText((u8) j) != NULL) {\n"
        "        total++;\n"
        "    }\n"
        "}\n"
    )

    axis, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert axis.status == "evaluated"
    variant = next(
        row for row in variants if row.operator == "inline-boundary-call-result-temp"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "char* ib_probe_call_result_0 = GetNameText((u8) j);" in text
    assert "if (ib_probe_call_result_0 != NULL)" in text
    assert "        total++;" in text
    assert variant.metadata["callee"] == "GetNameText"
    assert variant.metadata["return_type"] == "char*"


def test_inline_boundary_generates_call_result_temp_for_member_access(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int i, int j)\n"
        "{\n"
        "    total += GetPersistentNameData((u8) i)->vs_kos[(u8) j];\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    variant = next(
        row for row in variants if row.operator == "inline-boundary-call-result-temp"
    )
    text = Path(variant.source_retained or "").read_text()
    assert (
        "struct NameTagData* ib_probe_call_result_0 = "
        "GetPersistentNameData((u8) i);"
    ) in text
    assert "total += ib_probe_call_result_0->vs_kos[(u8) j];" in text


def test_inline_boundary_skips_call_result_temp_for_else_if_condition(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int j)\n"
        "{\n"
        "    if (j == 0) {\n"
        "        total++;\n"
        "    } else if (GetNameText((u8) j) != NULL) {\n"
        "        total += 2;\n"
        "    }\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert not any(
        row.operator == "inline-boundary-call-result-temp" for row in variants
    )


def test_inline_boundary_skips_call_result_temp_for_loop_header(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int j)\n"
        "{\n"
        "    while (GetNameText((u8) j) != NULL) {\n"
        "        j++;\n"
        "    }\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert not any(
        row.operator == "inline-boundary-call-result-temp" for row in variants
    )


def test_inline_boundary_skips_call_result_temp_for_for_loop_header(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int j)\n"
        "{\n"
        "    for (; GetNameText((u8) j) != NULL; j++) {\n"
        "        total++;\n"
        "    }\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert not any(
        row.operator == "inline-boundary-call-result-temp" for row in variants
    )


def test_inline_boundary_generates_call_result_temp_for_multiline_if(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int j)\n"
        "{\n"
        "    if (\n"
        "        GetNameText((u8) j) != NULL\n"
        "    ) {\n"
        "        total += 2;\n"
        "    }\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    variant = next(
        row for row in variants if row.operator == "inline-boundary-call-result-temp"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "char* ib_probe_call_result_0 = GetNameText((u8) j);" in text
    assert "ib_probe_call_result_0 != NULL" in text
    assert "        total += 2;" in text


def test_inline_boundary_skips_call_result_temp_for_declaration_and_lhs(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int i, int j, int value)\n"
        "{\n"
        "    char* text = GetNameText((u8) j);\n"
        "    GetPersistentNameData((u8) i)->slot = value;\n"
        "    sink(text);\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert not any(
        row.operator == "inline-boundary-call-result-temp" for row in variants
    )


def test_inline_boundary_skips_call_result_temp_for_nested_lhs_assignment(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int i, int value)\n"
        "{\n"
        "    if ((GetPersistentNameData((u8) i)->slot = value) != 0) {\n"
        "        total++;\n"
        "    }\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert not any(
        row.operator == "inline-boundary-call-result-temp" for row in variants
    )


def test_inline_boundary_call_result_temp_covers_allowlisted_return_types(
    tmp_path: Path,
) -> None:
    source = (
        "void fn_80000000(int i, int j)\n"
        "{\n"
        "    total += GetPersistentFighterData((u8) i)->ko_count;\n"
        "    sink(mnDiagram_GetFighterByIndex((u8) j));\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    generated = [
        row for row in variants if row.operator == "inline-boundary-call-result-temp"
    ]
    assert {row.metadata["return_type"] for row in generated} >= {
        "struct FighterData*",
        "u8",
    }
    text = "\n".join(Path(row.source_retained or "").read_text() for row in generated)
    assert (
        "struct FighterData* ib_probe_call_result_0 = "
        "GetPersistentFighterData((u8) i);"
    ) in text
    assert (
        "u8 ib_probe_call_result_1 = mnDiagram_GetFighterByIndex((u8) j);"
    ) in text


def test_inline_boundary_generates_popup_text_setup_helper(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(HSD_GObj* gobj, int slot)\n"
        "{\n"
        "    PopupData* data = gobj->user_data;\n"
        "    AnimTable* tbl = &table;\n"
        "    Point3d pos;\n"
        "    HSD_Text* text;\n"
        "    text = HSD_SisLib_803A6754(0, 1);\n"
        "    data->text[0] = text;\n"
        "    lb_8000B1CC(data->jobjs[8], &tbl->points[0], &pos);\n"
        "    text->font_size.x = 0.0521f;\n"
        "    text->font_size.y = 0.0521f;\n"
        "    text->default_alignment = 0;\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    variant = next(
        row
        for row in variants
        if row.operator == "inline-boundary-popup-text-setup-helper"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "static inline HSD_Text* ib_probe_popup_text_setup_0" in text
    assert "ib_probe_popup_text_setup_0(data, tbl, &pos" in text
    assert variant.metadata["family"] == "popup-text-setup-helper"


def test_inline_boundary_generates_popup_number_format_helper(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(HSD_Text* text, char* buf, int arg1, int arg2)\n"
        "{\n"
        "    u16 kos;\n"
        "    kos = GetPersistentNameData((u8) arg1)->vs_kos[(u8) arg2];\n"
        "    mnDiagram_IntToStr(buf, kos);\n"
        "    HSD_SisLib_803A6B98(text, 0.0f, 0.0f, buf);\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    variant = next(
        row
        for row in variants
        if row.operator == "inline-boundary-popup-number-format-helper"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "static inline void ib_probe_popup_number_format_0" in text
    assert "ib_probe_popup_number_format_0(text, buf, kos);" in text
    assert variant.metadata["family"] == "popup-number-format-helper"


def test_inline_boundary_generates_sort_entry_init_helper(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(void)\n"
        "{\n"
        "    mnDiagram2_SortEntry entries[25];\n"
        "    mnDiagram2_SortEntry* ptr;\n"
        "    int i;\n"
        "    int zero;\n"
        "    ptr = entries;\n"
        "    i = 0;\n"
        "    zero = 0;\n"
        "    do {\n"
        "        ptr->name = mnDiagram_GetFighterByIndex(i);\n"
        "        i++;\n"
        "        ptr->xC = zero;\n"
        "        ptr->x8 = zero;\n"
        "        ptr++;\n"
        "    } while (i < 25);\n"
        "}\n"
    )

    _, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=8,
    )

    variant = next(
        row
        for row in variants
        if row.operator == "inline-boundary-sort-entry-init-helper"
    )
    text = Path(variant.source_retained or "").read_text()
    assert "static inline void ib_probe_sort_entry_init_0" in text
    assert "ib_probe_sort_entry_init_0(entries, zero);" in text
    assert "ptr = entries + 25;" in text
    assert "i = 25;" in text
    assert variant.metadata["family"] == "sort-entry-init-helper"
    assert variant.metadata["helper"] == "ib_probe_sort_entry_init_0"
    assert variant.metadata["entry_array"] == "entries"
    assert variant.metadata["pointer_variable"] == "ptr"
    assert variant.metadata["index_variable"] == "i"
    assert variant.metadata["zero_variable"] == "zero"
    assert variant.metadata["touched_lines"] == {"start": 7, "end": 16}


def test_inline_boundary_rejects_preprocessor_regions(tmp_path: Path) -> None:
    source = (
        "void fn_80000000(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "#if 1\n"
        "    HSD_JObjSetTranslateY(jobj, y);\n"
        "#endif\n"
        "}\n"
        "\n"
        "static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    jobj->translate.y = y;\n"
        "}\n"
    )

    axis, variants = generate_inline_boundary_variants(
        source,
        "fn_80000000",
        tmp_path,
        baseline_percent=None,
        max_candidates=4,
    )

    assert not variants
    assert axis.status == "blocked"
    assert axis.blocker == "unsafe-inline-boundary-preprocessor"


def test_inline_boundary_scoring_retains_compile_and_checkdiff_status(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "void fn_80000000(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    HSD_JObjSetTranslateY(jobj, y);\n"
        "}\n"
        "\n"
        "static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y)\n"
        "{\n"
        "    jobj->translate.y = y;\n"
        "}\n"
    )

    def score_runner(variants: list[StructureVariant]) -> list[StructureScoreResult]:
        return [
            StructureScoreResult(
                label=variant.label,
                baseline_percent=80.0,
                candidate_percent=81.0,
                compile_status="ok",
                checkdiff_status="ok",
            )
            for variant in variants
        ]

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("inline-boundary",),
        max_candidates=2,
        score_variants=True,
        score_runner=score_runner,
    )

    assert payload["variants"]
    assert all(row["compile_status"] == "ok" for row in payload["variants"])
    assert all(row["checkdiff_status"] == "ok" for row in payload["variants"])


def test_run_structure_search_stop_condition_uses_hidden_unscored_candidates(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        _statement_source(
            "    unsigned int size;\n"
            "    int first;\n"
            "    int second;\n"
            "    size = (size << 8) | p[3];\n"
            "    return size + first + second;\n"
        )
    )

    def decl_order_runner(**kwargs):
        return {
            "baseline_pct": 80.0,
            "results": [
                {
                    "label": "non-improving",
                    "strategy": "swap",
                    "match_pct": 79.0,
                    "delta": -1.0,
                    "skipped": False,
                }
            ],
        }

    payload = run_structure_search(
        "fn_80000000",
        source_path,
        tmp_path / "structure",
        axes=("decl-order", "statement-order"),
        max_candidates=1,
        decl_order_runner=decl_order_runner,
    )

    assert len(payload["variants"]) == 1
    assert payload["variants"][0]["axis"] == "decl-order"
    assert payload["stop_condition"]["kind"] == "candidates-generated"


def _switch_source(body: str) -> str:
    return (
        "int fn_80000000(int mode)\n"
        "{\n"
        f"{body}"
        "}\n"
    )


def test_case_order_generates_adjacent_promote_demote_candidates(
    tmp_path: Path,
) -> None:
    source = _switch_source(
        "    switch (mode) {\n"
        "    case 0:\n"
        "        return 1;\n"
        "    case 1:\n"
        "        return 2;\n"
        "    case 2:\n"
        "        return 3;\n"
        "    }\n"
        "    return 0;\n"
    )

    axis, variants = generate_case_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=25.0,
        max_candidates=8,
    )

    assert axis.status == "evaluated"
    assert axis.candidate_count >= 4
    assert {variant.operator for variant in variants} >= {
        "case-order-adjacent-swap",
        "case-order-promote",
        "case-order-demote",
    }
    assert variants[0].source_retained is not None
    retained = Path(variants[0].source_retained)
    assert retained.exists()
    text = retained.read_text()
    assert "case 1:" in text
    assert "case 0:" in text
    assert variants[0].metadata["original_labels"] == ["0", "1", "2"]


def test_case_order_deduplicates_candidate_orders_before_cap(tmp_path: Path) -> None:
    source = _switch_source(
        "    switch (mode) {\n"
        "    case 0:\n"
        "        return 1;\n"
        "    case 1:\n"
        "        return 2;\n"
        "    case 2:\n"
        "        return 3;\n"
        "    case 3:\n"
        "        return 4;\n"
        "    }\n"
        "    return 0;\n"
    )

    axis, variants = generate_case_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=25.0,
        max_candidates=6,
    )

    assert axis.candidate_count == 6
    orders = [tuple(variant.metadata["case_order"]) for variant in variants]
    assert len(orders) == len(set(orders))


def test_case_order_allows_identifier_case_labels(tmp_path: Path) -> None:
    source = _switch_source(
        "    switch (mode) {\n"
        "    case FOO:\n"
        "        return 1;\n"
        "    case BAR:\n"
        "        return 2;\n"
        "    }\n"
        "    return 0;\n"
    )

    axis, variants = generate_case_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=25.0,
    )

    assert axis.status == "evaluated"
    assert variants
    assert variants[0].metadata["original_labels"] == ["FOO", "BAR"]


def test_case_order_treats_grouped_labels_as_one_arm(tmp_path: Path) -> None:
    source = _switch_source(
        "    switch (mode) {\n"
        "    case 0:\n"
        "    case 1:\n"
        "        return 2;\n"
        "    case 2:\n"
        "        return 3;\n"
        "    }\n"
        "    return 0;\n"
    )

    _axis, variants = generate_case_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=25.0,
        max_candidates=4,
    )

    assert variants
    assert variants[0].source_retained is not None
    text = Path(variants[0].source_retained).read_text()
    assert text.index("case 0:") < text.index("case 1:")


def test_case_order_rejects_fallthrough_preprocessor_and_nested_switch(
    tmp_path: Path,
) -> None:
    unsafe_sources = [
        _switch_source(
            "    switch (mode) {\n"
            "    case 0:\n"
            "        mode++; /* fallthrough */\n"
            "    case 1:\n"
            "        return 2;\n"
            "    }\n"
        ),
        _switch_source(
            "    switch (mode) {\n"
            "#if 1\n"
            "    case 0:\n"
            "        return 1;\n"
            "#endif\n"
            "    case 1:\n"
            "        return 2;\n"
            "    }\n"
        ),
        _switch_source(
            "    switch (mode) {\n"
            "    case 0:\n"
            "        switch (mode + 1) { case 9: return 9; }\n"
            "    case 1:\n"
            "        return 2;\n"
            "    }\n"
        ),
    ]
    for source in unsafe_sources:
        axis, variants = generate_case_order_variants(
            source,
            "fn_80000000",
            output_dir=tmp_path,
            baseline_percent=25.0,
        )
        assert variants == []
        assert axis.status == "blocked"
        assert axis.blocker in {
            "unsafe-switch-fallthrough",
            "unsafe-switch-preprocessor",
            "unsafe-switch-nested-ambiguous",
        }


def test_case_order_rejects_cross_label_goto_switch(tmp_path: Path) -> None:
    source = _switch_source(
        "    switch (mode) {\n"
        "again:\n"
        "    case 0:\n"
        "        goto again;\n"
        "    case 1:\n"
        "        return 2;\n"
        "    }\n"
    )

    axis, variants = generate_case_order_variants(
        source,
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=25.0,
    )

    assert variants == []
    assert axis.status == "blocked"
    assert axis.blocker == "unsafe-switch-cross-label"


def test_case_order_rejects_missing_function(tmp_path: Path) -> None:
    axis, variants = generate_case_order_variants(
        "int other(void) { return 0; }\n",
        "fn_80000000",
        output_dir=tmp_path,
        baseline_percent=25.0,
    )

    assert variants == []
    assert axis.blocker == "source-unavailable"
