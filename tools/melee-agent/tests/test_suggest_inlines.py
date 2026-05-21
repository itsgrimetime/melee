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
    assert "    void* cursor_jobj_arg_temp;" in patch.patched_source
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
    assert "    void* cursor_jobj_arg_temp;" in patched
    assert "cursor_jobj_arg_temp = cursor_jobj;" in patched
    assert "HSD_JObjSetTranslateX(cursor_jobj_arg_temp, x);" in patched
    assert "HSD_JObjSetTranslateX(void*" not in patched


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
