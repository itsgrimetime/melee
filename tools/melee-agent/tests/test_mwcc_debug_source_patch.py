"""Tests for source_patch.find_function / extract_function / replace_function."""

from __future__ import annotations

from src.mwcc_debug.source_patch import (
    extract_function,
    find_function,
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
