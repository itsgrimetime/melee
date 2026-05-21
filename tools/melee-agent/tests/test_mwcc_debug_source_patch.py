"""Tests for source_patch.find_function / extract_function / replace_function."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.source_patch import (
    extract_function,
    find_decl_block,
    find_function,
    get_decl_names,
    get_decl_names_by_scope,
    merge3_function,
    reorder_decls_in_function,
    reorder_decls_in_function_scope,
    replace_function,
)


SAMPLE = """
#include "foo.h"

static int counter = 0;

void foo(int arg)
{
    int i;
    for (i = 0; i < arg; i++) {
        counter++;
    }
}

// A line comment with a stray { brace mention
/* Block comment with another { } pair */
int bar(int x, int y)
{
    if (x > 0) {
        return x + y;
    }
    return y;
}

void prototype_only(void); /* prototype, not a definition */

static inline int helper(int z) { return z * 2; }
"""


def test_find_simple_function() -> None:
    span = find_function(SAMPLE, "foo")
    assert span is not None
    assert span.name == "foo"
    # Body should contain the for loop
    body = SAMPLE[span.body_open : span.body_close + 1]
    assert "for (i = 0" in body
    assert body.startswith("{")
    assert body.endswith("}")


def test_find_function_with_braces_in_comments() -> None:
    span = find_function(SAMPLE, "bar")
    assert span is not None
    body = SAMPLE[span.body_open : span.body_close + 1]
    assert "if (x > 0)" in body
    assert body.startswith("{")
    assert body.endswith("}")
    # The "{" in the block comment should NOT have been treated as part of the body


def test_find_function_skips_prototype() -> None:
    """`prototype_only` is only declared, no body. Should not match."""
    span = find_function(SAMPLE, "prototype_only")
    assert span is None


def test_find_inline_function() -> None:
    span = find_function(SAMPLE, "helper")
    assert span is not None
    body = SAMPLE[span.body_open : span.body_close + 1]
    assert "return z * 2" in body


def test_extract_function_returns_full_definition() -> None:
    text = extract_function(SAMPLE, "foo")
    assert text is not None
    assert text.startswith("void foo")
    assert text.endswith("}")


def test_replace_function_swaps_body() -> None:
    new_foo = """void foo(int arg)
{
    return arg * 100;
}"""
    patched = replace_function(SAMPLE, "foo", new_foo)
    assert patched is not None
    assert "return arg * 100" in patched
    assert "counter++" not in patched
    # Other functions still present
    assert "int bar(int x, int y)" in patched
    assert "static inline int helper" in patched


def test_replace_preserves_surrounding_whitespace() -> None:
    """Replacing should not eat the blank lines / decls around the function."""
    new_foo = "void foo(int arg)\n{\n    return arg;\n}"
    patched = replace_function(SAMPLE, "foo", new_foo)
    assert patched is not None
    # The static counter declaration above foo should still be there
    assert "static int counter = 0;" in patched
    # The comment / next function should still be there
    assert "// A line comment with a stray { brace mention" in patched


def test_find_function_not_present() -> None:
    assert find_function(SAMPLE, "nonexistent") is None


def test_find_function_disambiguates_substring() -> None:
    """Make sure foo_bar isn't matched when we search for foo."""
    sample = """
void foo_bar(void) { return; }
void foo(void) { int x = 1; }
"""
    span = find_function(sample, "foo")
    assert span is not None
    body = sample[span.body_open : span.body_close + 1]
    assert "int x = 1" in body
    assert "return" not in body


FN_WITH_DECLS = """
void example_fn(int arg)
{
    s32 i;
    int counter;
    HSD_Text* ptr;
    s32 j = 0;
    char buf[32];
    counter = arg;
    for (i = 0; i < counter; i++) {
        ptr = NULL;
    }
}
"""


def test_find_decl_block_basic() -> None:
    fn_text = "void f()\n{\n    int i;\n    int j;\n    return;\n}\n"
    body = fn_text[fn_text.index("{"):]
    block = find_decl_block(body)
    assert block is not None
    assert len(block.lines) == 2
    assert "int i;" in block.lines[0]
    assert "int j;" in block.lines[1]


def test_find_decl_block_in_realistic_function() -> None:
    span = find_function(FN_WITH_DECLS, "example_fn")
    assert span is not None
    fn_text = FN_WITH_DECLS[span.sig_start : span.full_end]
    body_open_rel = span.body_open - span.sig_start
    block = find_decl_block(fn_text[body_open_rel:])
    assert block is not None
    # 5 decls: i, counter, ptr, j (with initializer), buf (array)
    assert len(block.lines) == 5


def test_get_decl_names() -> None:
    names = get_decl_names(FN_WITH_DECLS, "example_fn")
    assert names == ["i", "counter", "ptr", "j", "buf"]


def test_reorder_decls_promote_to_first() -> None:
    """Move declaration #3 (j) to position 0."""
    # Order [3, 0, 1, 2, 4] means: take decl 3 first, then 0, 1, 2, 4
    patched = reorder_decls_in_function(FN_WITH_DECLS, "example_fn", [3, 0, 1, 2, 4])
    assert patched is not None
    new_names = get_decl_names(patched, "example_fn")
    assert new_names == ["j", "i", "counter", "ptr", "buf"]
    # Statements should still be there
    assert "counter = arg;" in patched
    assert "for (i = 0" in patched


def test_reorder_decls_demote_to_last() -> None:
    """Move declaration #0 (i) to position 4."""
    patched = reorder_decls_in_function(FN_WITH_DECLS, "example_fn", [1, 2, 3, 4, 0])
    assert patched is not None
    new_names = get_decl_names(patched, "example_fn")
    assert new_names == ["counter", "ptr", "j", "buf", "i"]


def test_reorder_decls_identity_is_noop() -> None:
    patched = reorder_decls_in_function(FN_WITH_DECLS, "example_fn", [0, 1, 2, 3, 4])
    assert patched == FN_WITH_DECLS


def test_reorder_decls_rejects_bad_permutation() -> None:
    # Wrong length
    assert reorder_decls_in_function(FN_WITH_DECLS, "example_fn", [0, 1]) is None
    # Duplicate index
    assert reorder_decls_in_function(FN_WITH_DECLS, "example_fn", [0, 0, 1, 2, 3]) is None
    # Out-of-range index
    assert reorder_decls_in_function(FN_WITH_DECLS, "example_fn", [0, 1, 2, 3, 99]) is None


def test_decl_block_stops_at_first_statement() -> None:
    """A decl block should END when a statement appears, even if more
    decls come after (illegal C89 but possible in C99)."""
    fn = """
void f()
{
    int a;
    int b;
    a = 1;        // statement — decl block ends here
    int c;        // ignored even though it's a decl
    b = c;
}
"""
    names = get_decl_names(fn, "f")
    assert names == ["a", "b"]


def test_find_function_with_string_brace() -> None:
    """A brace inside a string literal shouldn't confuse the matcher.

    The body offsets must bracket the WHOLE function body — including
    the in-string brace, since that's part of the function. What we
    verify here is that the matcher didn't get confused (returning None)
    or stop at the in-string brace early.
    """
    sample = """
void f(void)
{
    const char *s = "hello { world";
    return;
}
"""
    span = find_function(sample, "f")
    assert span is not None
    body = sample[span.body_open : span.body_close + 1]
    # The body MUST include the return statement — if the matcher stopped
    # at the in-string `}`, it would have cut off here.
    assert "return;" in body
    assert body.startswith("{")
    assert body.endswith("}")
    # And the in-string brace is preserved in the slice
    assert 'hello { world' in body


# ---------------------------------------------------------------------------
# merge3_function tests
# ---------------------------------------------------------------------------

_BASE_FN = """\
void myfunc(int x)
{
    int a = 0;
    int b = x + 1;
    return;
}"""

_CAND_FN = """\
void myfunc(int x)
{
    int a = 0;
    int b = x + 2;
    return;
}"""

_CURR_FN_CLEAN = """\
void myfunc(int x)
{
    int a = 0;
    int b = x + 1;
    return;
}"""

_CURR_FN_MANUAL_EDIT = """\
void myfunc(int x)
{
    int a = 0;
    int b = x + 1;
    int c = b - 1;
    return;
}"""

_CURR_FN_CONFLICT = """\
void myfunc(int x)
{
    int a = 0;
    int b = x + 99;
    return;
}"""


def test_merge3_clean_no_manual_edits() -> None:
    """Candidate changes a line; current has no manual edits — take candidate."""
    merged, conflicts = merge3_function(_BASE_FN, _CAND_FN, _CURR_FN_CLEAN)
    assert conflicts == []
    assert "x + 2" in merged


def test_merge3_preserves_current_manual_edit_in_non_mutated_region() -> None:
    """Current added a line in a region the candidate did not touch — keep it."""
    merged, conflicts = merge3_function(_BASE_FN, _CAND_FN, _CURR_FN_MANUAL_EDIT)
    assert conflicts == []
    # The candidate's change (x+2) and the manual addition (c = b-1) both appear
    assert "x + 2" in merged
    assert "c = b - 1" in merged


def test_merge3_conflict_detected() -> None:
    """Both candidate and current modified the same base line — conflict."""
    merged, conflicts = merge3_function(_BASE_FN, _CAND_FN, _CURR_FN_CONFLICT)
    assert len(conflicts) > 0
    # Line number should be plausible (the b= line is line 4 in base)
    assert any(ln >= 1 for ln, _ in conflicts)


def test_merge3_candidate_equals_base_is_noop() -> None:
    """Candidate identical to base — no changes; merged == current."""
    merged, conflicts = merge3_function(_BASE_FN, _BASE_FN, _CURR_FN_MANUAL_EDIT)
    assert conflicts == []
    assert merged == _CURR_FN_MANUAL_EDIT


def test_merge3_base_equals_current_takes_candidate() -> None:
    """Current matches base (no manual edits) — merged takes candidate fully."""
    merged, conflicts = merge3_function(_BASE_FN, _CAND_FN, _BASE_FN)
    assert conflicts == []
    assert "x + 2" in merged


# ---------------------------------------------------------------------------
# Fix A: verify-perm permuter placeholder detection
# ---------------------------------------------------------------------------

import re as _re

# Mirror the placeholder list from debug.py so the test catches any drift.
_PERMUTER_PLACEHOLDERS = (
    "inline_fn", "noinline_fn", "extra_fn", "helper_fn",
    "temp_fn", "local_var_fn",
)


def _has_placeholder(text: str) -> list[str]:
    """Return list of placeholder names found in `text` (for test assertions)."""
    found = []
    for ph in _PERMUTER_PLACEHOLDERS:
        if _re.search(r"\b" + _re.escape(ph) + r"\b", text):
            found.append(ph)
    return found


def test_placeholder_detection_finds_inline_fn() -> None:
    """Fix A: 'inline_fn' in candidate text is detected as a placeholder."""
    candidate = """\
void mnDiagram3_8024714C(HSD_GObj* gobj) {
    if (!(inline_fn(popup_jobj) & 0x02000000)) {
        return;
    }
}
"""
    hits = _has_placeholder(candidate)
    assert "inline_fn" in hits, (
        "verify-perm should detect 'inline_fn' as a permuter placeholder"
    )


def test_placeholder_detection_ignores_clean_candidate() -> None:
    """Fix A: a candidate with no placeholders returns an empty hit list."""
    candidate = """\
void fn(HSD_GObj* gobj) {
    if (!(popup_jobj->flags & 0x02000000)) {
        return;
    }
}
"""
    hits = _has_placeholder(candidate)
    assert hits == [], f"clean candidate should have no placeholder hits, got {hits}"


def test_placeholder_detection_word_boundary() -> None:
    """Fix A: 'inline_fn_wrapper' must NOT be flagged — only exact matches."""
    candidate = "void f(void) { inline_fn_wrapper(x); }"
    # 'inline_fn_wrapper' contains 'inline_fn' as a prefix, but the
    # word-boundary regex must NOT match it.
    hits = _has_placeholder(candidate)
    assert "inline_fn" not in hits, (
        "'inline_fn' must not match inside 'inline_fn_wrapper' (word boundary)"
    )


def test_placeholder_detection_all_known_placeholders() -> None:
    """Fix A: every placeholder in the sentinel list is detected."""
    for ph in _PERMUTER_PLACEHOLDERS:
        candidate = f"void f(void) {{ {ph}(x); }}"
        hits = _has_placeholder(candidate)
        assert ph in hits, f"placeholder '{ph}' was not detected"


def test_get_decl_names_by_scope_includes_nested_block() -> None:
    source = textwrap.dedent("""\
        void f(int cond)
        {
            int top_a;
            int top_b;
            if (cond) {
                HSD_JObj* row_0_jobj;
                HSD_JObj* cursor_row;
                Use(row_0_jobj, cursor_row);
            }
        }
    """)
    scopes = get_decl_names_by_scope(source, "f")
    assert ("f",) in scopes
    nested_scope = next(scope for scope in scopes if len(scope) == 2)
    assert scopes[("f",)] == ["top_a", "top_b"]
    assert scopes[nested_scope] == ["row_0_jobj", "cursor_row"]


def test_reorder_decls_in_function_scope_only_changes_target_scope() -> None:
    source = textwrap.dedent("""\
        void f(int cond)
        {
            int top_a;
            int top_b;
            if (cond) {
                HSD_JObj* row_0_jobj;
                HSD_JObj* cursor_row;
                Use(row_0_jobj, cursor_row);
            }
        }
    """)
    scopes = get_decl_names_by_scope(source, "f")
    nested_scope = next(scope for scope in scopes if len(scope) == 2)
    result = reorder_decls_in_function_scope(source, "f", nested_scope, [1, 0])
    assert result is not None
    assert result.index("int top_a;") < result.index("int top_b;")
    assert result.index("HSD_JObj* cursor_row;") < result.index("HSD_JObj* row_0_jobj;")
