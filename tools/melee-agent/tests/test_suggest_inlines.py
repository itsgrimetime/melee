"""Tests for suggest-inlines candidate generation and rendering."""
from __future__ import annotations

import json
import textwrap

from src.mwcc_debug.suggest_inlines import (
    generate_candidates,
    generate_patches,
    render_json,
    render_text,
    run,
)


def test_generate_candidates_from_repeated_call_groups() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* a, HSD_JObj* b)
        {
            HSD_JObjSetTranslateX(a, 1.0f);
            HSD_JObjSetMtxDirtySub(a);
            HSD_JObjSetTranslateX(b, 2.0f);
            HSD_JObjSetMtxDirtySub(b);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="repeated",
        max_span_statements=2,
        budget=8,
    )
    assert candidates
    assert any(c.kind == "void-helper" for c in candidates)
    assert all(c.anchor.kind == "repeated" for c in candidates)


def test_repeated_call_group_rejects_return_before_live_statement() -> None:
    source = textwrap.dedent("""\
        void f(Fighter* fp, int flag)
        {
            if (flag) {
                return;
            }
            ftCo_8009CB40(fp, 0, 1, NULL);
            if (flag) {
                return;
            }
            ftCo_8009CB40(fp, 1, 1, NULL);
        }
    """)

    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="repeated",
        max_span_statements=2,
        budget=8,
    )

    assert not [
        c for c in candidates
        if c.kind == "void-helper"
        and "return;" in c.source_excerpt
        and "ftCo_8009CB40" in c.source_excerpt
        and not c.is_rejected
    ]


def test_generate_arg_temp_candidate_for_named_call() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    assert any(c.kind == "arg-temp" and "cursor_jobj" in c.reads for c in candidates)


def test_generate_hidden_dirty_arg_temp_for_translate_inline() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj, f32 x)
        {
            HSD_JObjSetTranslateX(cursor_jobj, x);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )

    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp")
    assert candidate.reads == ("cursor_jobj",)
    assert candidate.metadata["visible_call"] == "HSD_JObjSetTranslateX"
    assert candidate.metadata["hidden_call"] == "HSD_JObjSetMtxDirtySub"


def test_generate_hidden_dirty_arg_temp_inside_direct_inline_helper() -> None:
    source = textwrap.dedent("""\
        static inline void SetCursor(HSD_JObj* cursor_jobj, f32 x)
        {
            HSD_JObjSetTranslateX(cursor_jobj, x);
        }

        void f(HSD_JObj* jobj)
        {
            SetCursor(jobj, 1.0f);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )

    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp")
    assert candidate.anchor.function == "f"
    assert candidate.anchor.scope_path == ("SetCursor",)
    assert candidate.reads == ("cursor_jobj",)
    assert candidate.metadata["helper_function"] == "SetCursor"
    assert "HSD_JObjSetTranslateX" in candidate.source_excerpt


def test_generate_hidden_dirty_arg_temp_inside_helper_after_unicode_comment() -> None:
    source = textwrap.dedent("""\
        // Cursor helper — source comments may contain Unicode arrows →.
        static inline void SetCursor(HSD_JObj* cursor_jobj, f32 x)
        {
            HSD_JObjSetTranslateX(cursor_jobj,
                                  HSD_JObjGetTranslationX(cursor_jobj));
        }

        void f(HSD_JObj* jobj)
        {
            SetCursor(jobj, 1.0f);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )

    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp")
    assert candidate.anchor.scope_path == ("SetCursor",)
    assert candidate.reads == ("cursor_jobj",)


def test_coalesce_seed_uses_pattern_fallback_for_hidden_dirty_candidates() -> None:
    source = textwrap.dedent("""\
        // Cursor helper — source comments may contain Unicode arrows →.
        static inline void SetCursor(HSD_JObj* cursor_jobj, f32 x)
        {
            HSD_JObjSetTranslateX(cursor_jobj, x);
        }

        void f(HSD_JObj* jobj)
        {
            SetCursor(jobj, 1.0f);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="coalesce",
        max_span_statements=2,
        budget=8,
    )

    assert any(c.kind == "hidden-dirty-arg-temp" for c in candidates)


def test_generate_patches_for_arg_temp_candidate() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    arg_temp = next(c for c in candidates if c.kind == "arg-temp")
    patches = generate_patches(source, "f", [arg_temp])
    assert len(patches) == 1
    patch = patches[0]
    assert "cursor_jobj_arg_temp" in patch.patched_source
    assert "HSD_JObjSetMtxDirtySub(cursor_jobj_arg_temp);" in patch.patched_source
    assert "    HSD_JObj* cursor_jobj_arg_temp;" in patch.patched_source
    assert "void* cursor_jobj_arg_temp" not in patch.patched_source
    assert "HSD_JObjSetMtxDirtySub(void*" not in patch.patched_source


def test_generate_patches_for_hidden_dirty_arg_temp_candidate() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj, f32 x)
        {
            HSD_JObjSetTranslateX(cursor_jobj, x);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp")

    patches = generate_patches(source, "f", [candidate])

    assert len(patches) == 1
    patched = patches[0].patched_source
    assert "    HSD_JObj* cursor_jobj_arg_temp;" in patched
    assert "void* cursor_jobj_arg_temp" not in patched
    assert "cursor_jobj_arg_temp = cursor_jobj;" in patched
    assert "HSD_JObjSetTranslateX(cursor_jobj_arg_temp, x);" in patched
    assert "HSD_JObjSetTranslateX(void*" not in patched


def test_hidden_dirty_arg_temp_patch_uses_source_type_and_top_declaration() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj, f32 x)
        {
            int marker;
            marker = 0;
            HSD_JObjSetTranslateX(cursor_jobj, x);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp")

    patched = generate_patches(source, "f", [candidate])[0].patched_source

    assert "    HSD_JObj* cursor_jobj_arg_temp;\n    marker = 0;" in patched
    assert "void* cursor_jobj_arg_temp" not in patched
    assert "cursor_jobj_arg_temp = cursor_jobj;" in patched
    assert "HSD_JObjSetTranslateX(cursor_jobj_arg_temp, x);" in patched


def test_hidden_dirty_group_candidate_patches_xyz_together() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj, f32 x, f32 y, f32 z)
        {
            HSD_JObjSetTranslateX(cursor_jobj, x);
            HSD_JObjSetTranslateY(cursor_jobj, y);
            HSD_JObjSetTranslateZ(cursor_jobj, z);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp-group")

    patched = generate_patches(source, "f", [candidate])[0].patched_source

    assert patched.count("HSD_JObj* cursor_jobj_arg_temp;") == 1
    assert patched.count("cursor_jobj_arg_temp = cursor_jobj;") == 3
    assert "HSD_JObjSetTranslateX(cursor_jobj_arg_temp, x);" in patched
    assert "HSD_JObjSetTranslateY(cursor_jobj_arg_temp, y);" in patched
    assert "HSD_JObjSetTranslateZ(cursor_jobj_arg_temp, z);" in patched


def test_generate_patches_for_hidden_dirty_arg_temp_inside_helper() -> None:
    source = textwrap.dedent("""\
        static inline void SetCursor(HSD_JObj* cursor_jobj, f32 x)
        {
            HSD_JObjSetTranslateX(cursor_jobj, x);
        }

        void f(HSD_JObj* jobj)
        {
            SetCursor(jobj, 1.0f);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "hidden-dirty-arg-temp")

    patches = generate_patches(source, "f", [candidate])

    assert len(patches) == 1
    patched = patches[0].patched_source
    assert "HSD_JObj* cursor_jobj_arg_temp;" in patched
    assert "void* cursor_jobj_arg_temp" not in patched
    assert "cursor_jobj_arg_temp = cursor_jobj;" in patched
    assert "HSD_JObjSetTranslateX(cursor_jobj_arg_temp, x);" in patched
    assert "SetCursor(jobj, 1.0f);" in patched


def test_void_helper_patch_parameterizes_local_reads() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* jobj, HSD_Text* text, f32 x_spacing)
        {
            HSD_JObjSetTranslateX(jobj, x_spacing);
            HSD_TextSetPosition(text, x_spacing, 0.0f);
            HSD_JObjSetTranslateX(jobj, x_spacing);
            HSD_TextSetPosition(text, x_spacing, 0.0f);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="repeated",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(
        c for c in candidates
        if c.kind == "void-helper" and "HSD_TextSetPosition" in c.source_excerpt
    )

    patched = generate_patches(source, "f", [candidate])[0].patched_source

    assert "static inline void f_void_helper_" in patched
    assert "(HSD_Text* text, f32 x_spacing)" in patched
    assert "HSD_JObjSetTranslateX(jobj, x_spacing);" in patched
    assert "HSD_TextSetPosition(text, x_spacing, 0.0f);" in patched
    assert "(text, x_spacing);" in patched
    assert "HSD_JObjSetTranslateX(" not in candidate.reads


def test_generate_patches_uses_byte_offsets_safely_after_unicode_comment() -> None:
    source = textwrap.dedent("""\
        // Existing notes — these are before the function and use Unicode.
        void f(HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    arg_temp = next(c for c in candidates if c.kind == "arg-temp")

    patched = generate_patches(source, "f", [arg_temp])[0].patched_source

    assert "cursor_jobj_arg_temp = cursor_jobj;" in patched
    assert "HSD_JObjSetMtxDirtySub(cursor_jobj_arg_temp);" in patched
    assert "cucursor_jobj" not in patched


def test_generate_return_helper_patch_uses_byte_offsets_safely_after_unicode_comment() -> None:
    source = textwrap.dedent("""\
        // Existing notes — these are before the function and use Unicode.
        void f(void)
        {
            int inputs;
            inputs = GetInputs();
            Use(inputs);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "return-helper")

    patched = generate_patches(source, "f", [candidate])[0].patched_source

    assert "inputs = f_return_helper_" in patched
    assert "inininputs" not in patched
    assert "GetInputs()" in patched


def test_run_diagnostic_report_does_not_require_pcdump() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
        }
    """)
    report = run(
        source=source,
        function="f",
        pcdump_text="",
        seed_source="patterns",
        budget=8,
        max_span_statements=2,
        verify=False,
    )
    assert report.function == "f"
    assert report.candidates
    assert report.scores == []


def test_render_text_mentions_rejections_and_candidates() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
        }
    """)
    report = run(
        source=source,
        function="f",
        pcdump_text="",
        seed_source="patterns",
        budget=8,
        max_span_statements=2,
        verify=False,
    )
    out = render_text(report)
    assert "suggest-inlines" in out
    assert "f" in out
    assert "arg-temp" in out


def test_render_json_is_parseable() -> None:
    source = "void f(HSD_JObj* cursor_jobj) { HSD_JObjSetMtxDirtySub(cursor_jobj); }"
    report = run(
        source=source,
        function="f",
        pcdump_text="",
        seed_source="patterns",
        budget=8,
        max_span_statements=2,
        verify=False,
    )
    payload = json.loads(render_json(report))
    assert payload["function"] == "f"
    assert payload["candidates"]


def test_render_json_omits_full_patched_source_by_default() -> None:
    source = "void f(HSD_JObj* cursor_jobj) { HSD_JObjSetMtxDirtySub(cursor_jobj); }"
    report = run(
        source=source,
        function="f",
        pcdump_text="",
        seed_source="patterns",
        budget=8,
        max_span_statements=2,
        verify=False,
    )

    payload = json.loads(render_json(report))

    assert payload["patches"]
    assert "summary" in payload["patches"][0]
    assert "patched_source" not in payload["patches"][0]


def test_render_json_can_emit_full_patched_source() -> None:
    source = "void f(HSD_JObj* cursor_jobj) { HSD_JObjSetMtxDirtySub(cursor_jobj); }"
    report = run(
        source=source,
        function="f",
        pcdump_text="",
        seed_source="patterns",
        budget=8,
        max_span_statements=2,
        verify=False,
    )

    payload = json.loads(render_json(report, emit_patches=True))

    assert "patched_source" in payload["patches"][0]


def test_render_json_can_emit_patch_hunks_without_full_source() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
        }
    """)
    report = run(
        source=source,
        function="f",
        pcdump_text="",
        seed_source="patterns",
        budget=8,
        max_span_statements=2,
        verify=False,
    )

    payload = json.loads(render_json(report, emit_hunks=True))

    patch = payload["patches"][0]
    assert "hunk" in patch
    assert "@@" in patch["hunk"]
    assert "+    HSD_JObj* cursor_jobj_arg_temp;" in patch["hunk"]
    assert "patched_source" not in patch


def test_generate_return_helper_candidate_for_single_assignment() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* jobj)
        {
            f32 y;
            y = HSD_JObjGetTranslationY(jobj);
            Use(y);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "return-helper")
    assert candidate.writes == ("y",)
    assert candidate.metadata["return_type"] == "f32"
    assert candidate.metadata["rhs"] == "HSD_JObjGetTranslationY(jobj)"


def test_generate_patches_for_return_helper_candidate() -> None:
    source = textwrap.dedent("""\
        void f(HSD_JObj* jobj)
        {
            f32 y;
            y = HSD_JObjGetTranslationY(jobj);
            Use(y);
        }
    """)
    candidates = generate_candidates(
        source=source,
        function="f",
        seed_source="patterns",
        max_span_statements=2,
        budget=8,
    )
    candidate = next(c for c in candidates if c.kind == "return-helper")
    patches = generate_patches(source, "f", [candidate])
    assert len(patches) == 1
    patched = patches[0].patched_source
    assert "static inline f32 f_return_helper_" in patched
    assert "return HSD_JObjGetTranslationY(jobj);" in patched
    assert "y = f_return_helper_" in patched


def test_render_json_includes_scores() -> None:
    from src.mwcc_debug.source_shape import CandidateScore, SourceShapeReport

    report = SourceShapeReport(
        function="f",
        candidates=[],
        patches=[],
        scores=[
            CandidateScore(
                candidate_id="arg-temp-0001",
                compile_ok=True,
                checkdiff_pct=99.0,
                checkdiff_delta=0.1,
                pcdump_score_delta=None,
                diagnostics_path=None,
            )
        ],
    )
    payload = json.loads(render_json(report))
    assert payload["scores"][0]["candidate_id"] == "arg-temp-0001"
    assert payload["scores"][0]["checkdiff_delta"] == 0.1


def test_verify_real_tree_patches_marks_null_checkdiff_scores_unscored(tmp_path) -> None:
    from src.mwcc_debug.candidate_verify import (
        CheckdiffResult,
        verify_real_tree_patches,
    )
    from src.mwcc_debug.source_shape import CandidatePatch, SourceShapeReport

    source_path = tmp_path / "demo.c"
    source_path.write_text("void f(void) {}\n", encoding="utf-8")
    patches = [
        CandidatePatch(
            candidate_id="arg-temp-0001",
            patched_source="void f(void) { helper(); }\n",
            summary="extract helper",
            touched_ranges=((0, 1),),
        )
    ]

    scores = verify_real_tree_patches(
        function="f",
        source_path=source_path,
        patches=patches,
        checkdiff_runner=lambda _function: CheckdiffResult(None, None),
        apply_best=False,
        threshold=0.05,
        baseline_result=CheckdiffResult(None, None),
    )

    assert len(scores) == 1
    score = scores[0]
    assert score.compile_ok is True
    assert score.status == "unscored"
    assert score.score_reason == "candidate checkdiff did not return a match percent"
    payload = json.loads(render_json(SourceShapeReport(function="f", scores=scores)))
    assert payload["scores"][0]["status"] == "unscored"
    assert payload["scores"][0]["score_reason"] == (
        "candidate checkdiff did not return a match percent"
    )
    text = render_text(SourceShapeReport(function="f", scores=scores))
    assert "status=unscored" in text
    assert "candidate checkdiff did not return a match percent" in text


def test_render_text_scores_include_baseline_candidate_and_delta() -> None:
    from src.mwcc_debug import source_shape
    from src.mwcc_debug.source_shape import CandidateScore, SourceShapeReport

    assert hasattr(source_shape, "CandidateCopyTrace")

    report = SourceShapeReport(
        function="f",
        candidates=[],
        patches=[],
        scores=[
            CandidateScore(
                candidate_id="arg-temp-0001",
                compile_ok=True,
                checkdiff_pct=97.25,
                checkdiff_delta=0.0,
                pcdump_score_delta=None,
                diagnostics_path=None,
                checkdiff_baseline_pct=97.25,
                copy_traces=(
                    source_shape.CandidateCopyTrace(
                        from_virtual=50,
                        to_virtual=110,
                        status="copy-found",
                        likely_cause="removed-before-coloring",
                        first_copy_pass="BEFORE GLOBAL OPTIMIZATION",
                        last_copy_pass="AFTER PEEPHOLE FORWARD",
                        first_absent_pass="BEFORE REGISTER COLORING",
                        transform_category="copy-propagation-or-dead-copy",
                    ),
                ),
            )
        ],
    )

    out = render_text(report)

    assert "baseline=97.250" in out
    assert "candidate=97.250" in out
    assert "delta=+0.000" in out
    assert "copy r110<-r50" in out
    assert "removed-before-coloring" in out
    assert "first_absent=BEFORE REGISTER COLORING" in out


def test_render_text_summarizes_and_highlights_filtered_copy_traces() -> None:
    from src.mwcc_debug import source_shape
    from src.mwcc_debug.source_shape import CandidateScore, SourceShapeReport

    report = SourceShapeReport(
        function="f",
        candidates=[],
        patches=[],
        scores=[
            CandidateScore(
                candidate_id="hidden-dirty-arg-temp-group-0004",
                compile_ok=True,
                checkdiff_pct=97.25,
                checkdiff_delta=0.0,
                pcdump_score_delta=None,
                diagnostics_path=None,
                checkdiff_baseline_pct=97.25,
                copy_trace_total_count=57,
                copy_trace_omitted_count=54,
                copy_traces=(
                    source_shape.CandidateCopyTrace(
                        from_virtual=50,
                        to_virtual=110,
                        status="copy-found",
                        likely_cause="removed-before-coloring",
                        first_absent_pass="BEFORE REGISTER COLORING",
                        transform_category="copy-eliminated-before-coloring",
                        first_copy_block=245,
                        interest_reasons=(
                            "dominant-source-virtual",
                            "removed-before-coloring",
                        ),
                    ),
                    source_shape.CandidateCopyTrace(
                        from_virtual=50,
                        to_virtual=109,
                        status="copy-found",
                        likely_cause="removed-before-coloring",
                        first_copy_block=246,
                        interest_reasons=("dominant-source-virtual",),
                    ),
                    source_shape.CandidateCopyTrace(
                        from_virtual=50,
                        to_virtual=108,
                        status="copy-found",
                        likely_cause="removed-before-coloring",
                        first_copy_block=247,
                        interest_reasons=("dominant-source-virtual",),
                    ),
                ),
            )
        ],
    )

    out = render_text(report)

    assert "copy traces: showing 3/57 candidate-relevant traces (54 omitted)" in out
    assert "copy r110<-r50 [dominant-source-virtual, removed-before-coloring]" in out
    assert "block=245" in out


def test_copy_trace_summary_prefers_dominant_removed_source() -> None:
    from src.mwcc_debug import source_shape

    assert hasattr(source_shape, "summarize_candidate_copy_traces")
    traces = (
        source_shape.CandidateCopyTrace(
            from_virtual=50,
            to_virtual=110,
            status="copy-found",
            likely_cause="removed-before-coloring",
        ),
        source_shape.CandidateCopyTrace(
            from_virtual=50,
            to_virtual=109,
            status="copy-found",
            likely_cause="removed-before-coloring",
        ),
        source_shape.CandidateCopyTrace(
            from_virtual=50,
            to_virtual=108,
            status="copy-found",
            likely_cause="removed-before-coloring",
        ),
        source_shape.CandidateCopyTrace(
            from_virtual=70,
            to_virtual=120,
            status="copy-found",
            likely_cause="removed-before-coloring",
        ),
        source_shape.CandidateCopyTrace(
            from_virtual=71,
            to_virtual=121,
            status="copy-found",
            likely_cause="coalesced-in-coloring",
        ),
    )

    summary = source_shape.summarize_candidate_copy_traces(
        traces,
        max_traces=3,
    )

    assert summary.total_count == 5
    assert summary.omitted_count == 2
    assert [(t.to_virtual, t.from_virtual) for t in summary.traces] == [
        (108, 50),
        (109, 50),
        (110, 50),
    ]
    assert all(
        "dominant-source-virtual" in trace.interest_reasons
        for trace in summary.traces
    )


def test_copy_trace_summary_prioritizes_candidate_source_virtual() -> None:
    from src.mwcc_debug import source_shape

    traces = tuple(
        source_shape.CandidateCopyTrace(
            from_virtual=45,
            to_virtual=virtual,
            status="copy-found",
            likely_cause="removed-before-coloring",
            first_copy_block=100 + idx,
        )
        for idx, virtual in enumerate((135, 136, 137, 138))
    ) + (
        source_shape.CandidateCopyTrace(
            from_virtual=50,
            to_virtual=108,
            status="copy-found",
            likely_cause="removed-before-coloring",
            first_copy_block=245,
        ),
    )

    summary = source_shape.summarize_candidate_copy_traces(
        traces,
        max_traces=1,
        priority_virtuals=(50,),
    )

    assert [(trace.to_virtual, trace.from_virtual) for trace in summary.traces] == [
        (108, 50)
    ]
    assert "priority-virtual" in summary.traces[0].interest_reasons


def test_copy_trace_summary_prioritizes_patch_local_block() -> None:
    from src.mwcc_debug import source_shape

    traces = (
        source_shape.CandidateCopyTrace(
            from_virtual=45,
            to_virtual=135,
            status="copy-found",
            likely_cause="removed-before-coloring",
            first_copy_block=100,
        ),
        source_shape.CandidateCopyTrace(
            from_virtual=50,
            to_virtual=108,
            status="copy-found",
            likely_cause="removed-before-coloring",
            first_copy_block=245,
        ),
    )

    summary = source_shape.summarize_candidate_copy_traces(
        traces,
        max_traces=1,
        priority_blocks=(245,),
    )

    assert [(trace.to_virtual, trace.from_virtual) for trace in summary.traces] == [
        (108, 50)
    ]
    assert "patch-local-block" in summary.traces[0].interest_reasons


def test_copy_trace_summary_prefers_before_coloring_copy_over_late_disappear() -> None:
    from src.mwcc_debug import source_shape

    summary = source_shape.summarize_candidate_copy_traces(
        (
            source_shape.CandidateCopyTrace(
                from_virtual=71,
                to_virtual=80,
                status="copy-found",
                likely_cause="copy-survived-distinct-phys",
                transform_category="copy-survived",
                first_absent_pass="AFTER INSTRUCTION SCHEDULING",
                first_copy_block=100,
            ),
            source_shape.CandidateCopyTrace(
                from_virtual=50,
                to_virtual=108,
                status="copy-found",
                likely_cause="removed-before-coloring",
                transform_category="copy-eliminated-before-coloring",
                first_absent_pass="BEFORE REGISTER COLORING",
                first_copy_block=245,
            ),
        ),
        max_traces=1,
    )

    assert [(trace.to_virtual, trace.from_virtual) for trace in summary.traces] == [
        (108, 50)
    ]
    assert "removed-before-coloring" in summary.traces[0].interest_reasons


def test_copy_trace_summary_distinguishes_post_coloring_disappearances() -> None:
    from src.mwcc_debug import source_shape

    summary = source_shape.summarize_candidate_copy_traces((
        source_shape.CandidateCopyTrace(
            from_virtual=71,
            to_virtual=121,
            status="copy-found",
            likely_cause="copy-survived-distinct-phys",
            transform_category="copy-survived",
            first_absent_pass="AFTER INSTRUCTION SCHEDULING",
        ),
    ))

    assert "removed-before-coloring" not in summary.traces[0].interest_reasons
    assert "copy-disappears-after-coloring" in summary.traces[0].interest_reasons
