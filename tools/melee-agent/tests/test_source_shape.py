"""Tests for shared source-shape dataclasses."""
from __future__ import annotations

from pathlib import Path

from src.mwcc_debug.source_shape import (
    CandidatePatch,
    CandidateScore,
    InlineCandidate,
    SourceAnchor,
    SourceShapeReport,
    rank_scores,
)


def test_source_anchor_records_scope_and_reason() -> None:
    anchor = SourceAnchor(
        function="fn_test",
        scope_path=("fn_test", "block@l10c4"),
        byte_range=(100, 140),
        line_range=(10, 14),
        kind="repeated",
        reason="two setter blocks share call shape",
        virtuals=(46, 50),
    )
    assert anchor.function == "fn_test"
    assert anchor.scope_path == ("fn_test", "block@l10c4")
    assert anchor.virtuals == (46, 50)


def test_inline_candidate_defaults_to_accepted() -> None:
    anchor = SourceAnchor(
        function="fn_test",
        scope_path=("fn_test",),
        byte_range=(10, 20),
        line_range=(2, 3),
        kind="pattern",
        reason="call argument temp",
    )
    candidate = InlineCandidate(
        candidate_id="arg-temp-0001",
        kind="arg-temp",
        anchor=anchor,
        helper_name="fn_test_arg_temp_0001",
        reads=("jobj",),
        writes=(),
        source_excerpt="HSD_JObjSetMtxDirtySub(jobj);",
    )
    assert candidate.is_rejected is False
    assert candidate.rejection_reason is None


def test_inline_candidate_rejection_flag() -> None:
    anchor = SourceAnchor(
        function="fn_test",
        scope_path=("fn_test",),
        byte_range=(10, 30),
        line_range=(2, 4),
        kind="repeated",
        reason="contains label",
    )
    candidate = InlineCandidate(
        candidate_id="void-helper-0001",
        kind="void-helper",
        anchor=anchor,
        helper_name="fn_test_helper_0001",
        reads=(),
        writes=(),
        source_excerpt="label: x = 1;",
        rejection_reason="span contains label",
    )
    assert candidate.is_rejected is True


def test_rank_scores_prefers_compile_and_positive_delta() -> None:
    scores = [
        CandidateScore(
            candidate_id="bad-compile",
            compile_ok=False,
            checkdiff_pct=None,
            checkdiff_delta=None,
            pcdump_score_delta=None,
            diagnostics_path=Path("/tmp/bad.log"),
            candidate_size=1,
            helper_param_count=0,
        ),
        CandidateScore(
            candidate_id="small-win",
            compile_ok=True,
            checkdiff_pct=95.5,
            checkdiff_delta=0.05,
            pcdump_score_delta=0.0,
            diagnostics_path=None,
            candidate_size=2,
            helper_param_count=1,
        ),
        CandidateScore(
            candidate_id="big-win",
            compile_ok=True,
            checkdiff_pct=95.7,
            checkdiff_delta=0.2,
            pcdump_score_delta=0.0,
            diagnostics_path=None,
            candidate_size=5,
            helper_param_count=2,
        ),
    ]
    ranked = rank_scores(scores)
    assert [s.candidate_id for s in ranked] == [
        "big-win",
        "small-win",
        "bad-compile",
    ]


def test_source_shape_report_partitions_candidates() -> None:
    anchor = SourceAnchor(
        function="fn_test",
        scope_path=("fn_test",),
        byte_range=(1, 2),
        line_range=(1, 1),
        kind="pattern",
        reason="arg temp",
    )
    accepted = InlineCandidate(
        candidate_id="arg-temp-0001",
        kind="arg-temp",
        anchor=anchor,
        helper_name="fn_test_arg_temp_0001",
        reads=("x",),
        writes=(),
        source_excerpt="Call(x);",
    )
    rejected = InlineCandidate(
        candidate_id="void-helper-0002",
        kind="void-helper",
        anchor=anchor,
        helper_name="fn_test_helper_0002",
        reads=(),
        writes=(),
        source_excerpt="goto end;",
        rejection_reason="span contains goto",
    )
    report = SourceShapeReport(
        function="fn_test",
        candidates=[accepted, rejected],
        patches=[
            CandidatePatch(
                candidate_id="arg-temp-0001",
                patched_source="void fn_test(void) { int x; Call(x); }",
                summary="introduce temp",
                touched_ranges=((10, 20),),
            )
        ],
        scores=[],
    )
    assert [c.candidate_id for c in report.accepted_candidates] == ["arg-temp-0001"]
    assert [c.candidate_id for c in report.rejected_candidates] == ["void-helper-0002"]
