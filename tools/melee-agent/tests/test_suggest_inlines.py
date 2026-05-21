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
