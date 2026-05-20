"""Tests for the build-failure diagnostic extraction helpers in
`cli.debug` — used by `verify-perm`/`triage-perm` to surface the first
informative compiler error (Fix A).
"""

from __future__ import annotations

from src.cli.debug import (
    _extract_first_diagnostic,
    _extract_ninja_error,
)


def test_extract_first_diagnostic_standard_form() -> None:
    """A standard `filename:line:col: error: msg` line is returned verbatim."""
    out = (
        "[1/2] Compiling src/melee/mn/mnvibration.c\n"
        "src/melee/mn/mnvibration.c:42:7: error: undefined symbol 'foo'\n"
        "      ^^^^^^^^^\n"
    )
    diag = _extract_first_diagnostic(out, "")
    assert diag is not None
    assert "mnvibration.c:42:7" in diag
    assert "error" in diag
    assert "undefined symbol 'foo'" in diag


def test_extract_first_diagnostic_mwcc_block_form() -> None:
    """MWCC's pretty-printed multi-line block is synthesized into one line."""
    err = (
        "###############################################################\n"
        "# File: include/melee/mn.h\n"
        "# Line: 21\n"
        "# Error:           cannot find type \"foo\"\n"
    )
    diag = _extract_first_diagnostic("", err)
    assert diag is not None
    assert "include/melee/mn.h" in diag
    assert "21" in diag
    assert "cannot find type" in diag


def test_extract_first_diagnostic_none_when_no_error() -> None:
    """No error → returns None (lets callers fall back to last-line)."""
    out = (
        "[1/2] Compiling src/melee/mn/mnvibration.c\n"
        "[2/2] Linking\n"
    )
    assert _extract_first_diagnostic(out, "") is None


def test_extract_first_diagnostic_prefers_error_over_warning() -> None:
    """When warnings precede errors, the first ERROR is returned, not
    the first warning."""
    out = (
        "src/melee/foo.c:10:1: warning: implicit conversion\n"
        "src/melee/foo.c:42:7: error: undefined symbol 'bar'\n"
    )
    diag = _extract_first_diagnostic(out, "")
    assert diag is not None
    assert "error" in diag
    assert "undefined symbol 'bar'" in diag


def test_extract_ninja_error_promotes_first_diagnostic() -> None:
    """When many warnings precede the real error, the error line stays
    in the trimmed output (not lost to max_lines)."""
    # Build 10 warnings, then 1 error. With max_lines=8 the naive trim
    # would drop the error. Our extractor should promote it.
    warnings = "\n".join(
        f"src/foo.c:{i}: warning: unused variable 'x'"
        for i in range(10)
    )
    err_line = "src/foo.c:99:1: error: undefined symbol 'baz'"
    combined = warnings + "\n" + err_line + "\n      ^^^^^^^^^"
    out = _extract_ninja_error(combined, "")
    assert err_line in out, (
        f"Expected error line in result, got:\n{out}"
    )


def test_extract_ninja_error_no_diag_falls_back() -> None:
    """When no `filename:line: error:` is present, the original
    relevant-line logic still produces output (no crash)."""
    out = _extract_ninja_error("[1/2] Compiling foo.c\n", "")
    assert isinstance(out, str)
