from __future__ import annotations

import json
from pathlib import Path

import src.search.structure as structure_mod
from src.search.structure import (
    AxisSummary,
    StructureScoreResult,
    StructureVariant,
    generate_case_order_variants,
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
    assert {row["axis"] for row in payload["future_axes"]} == {
        "inline-boundary",
        "loop-shape-expanded",
    }
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
