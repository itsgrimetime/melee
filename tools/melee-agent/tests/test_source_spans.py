"""Tests for tree-sitter source span discovery."""
from __future__ import annotations

import textwrap

from src.mwcc_debug.source_spans import (
    find_call_argument_spans,
    find_repeated_call_groups,
    list_statement_spans,
    reject_reason_for_span_group,
)


def test_list_statement_spans_tracks_nested_scope() -> None:
    src = textwrap.dedent("""\
        void f(int cond, HSD_JObj* jobj)
        {
            int top;
            if (cond) {
                int nested;
                HSD_JObjSetMtxDirtySub(jobj);
            }
        }
    """)
    spans = list_statement_spans(src, "f")
    call_span = next(s for s in spans if "HSD_JObjSetMtxDirtySub" in s.text)
    assert call_span.scope_path[0] == "f"
    assert len(call_span.scope_path) == 2
    assert call_span.kind == "expression_statement"
    assert call_span.line_range[0] > 0


def test_list_statement_spans_records_reads_and_writes() -> None:
    src = textwrap.dedent("""\
        void f(void)
        {
            int x;
            int y;
            x = y + 1;
            Use(x);
        }
    """)
    spans = list_statement_spans(src, "f")
    assign = next(s for s in spans if "x = y + 1" in s.text)
    assert "x" in assign.writes
    assert "y" in assign.reads
    call = next(s for s in spans if "Use(x)" in s.text)
    assert call.reads == ("Use", "x")
    assert call.writes == ()


def test_find_repeated_call_groups_matches_same_call_shape() -> None:
    src = textwrap.dedent("""\
        void f(HSD_JObj* a, HSD_JObj* b)
        {
            HSD_JObjSetTranslateX(a, 1.0f);
            HSD_JObjSetMtxDirtySub(a);
            HSD_JObjSetTranslateX(b, 2.0f);
            HSD_JObjSetMtxDirtySub(b);
        }
    """)
    groups = find_repeated_call_groups(src, "f", max_span_statements=2)
    excerpts = ["\n".join(span.text for span in group.spans) for group in groups]
    assert any("HSD_JObjSetTranslateX" in e and "HSD_JObjSetMtxDirtySub" in e for e in excerpts)


def test_reject_reason_for_goto() -> None:
    src = textwrap.dedent("""\
        void f(int x)
        {
            if (x) {
                goto done;
            }
        done:
            return;
        }
    """)
    spans = list_statement_spans(src, "f")
    goto_span = next(s for s in spans if "goto done" in s.text)
    assert reject_reason_for_span_group([goto_span]) == "span contains goto"


def test_find_call_argument_spans_returns_each_argument() -> None:
    src = textwrap.dedent("""\
        void f(HSD_JObj* jobj, HSD_JObj* cursor_jobj)
        {
            HSD_JObjSetMtxDirtySub(cursor_jobj);
            HSD_JObjSetTranslateX(jobj, HSD_JObjGetTranslationX(cursor_jobj));
        }
    """)
    args = find_call_argument_spans(src, "f", "HSD_JObjSetTranslateX")
    texts = [arg.text for arg in args]
    assert "jobj" in texts
    assert "HSD_JObjGetTranslationX(cursor_jobj)" in texts
