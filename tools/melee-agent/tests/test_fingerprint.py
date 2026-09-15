"""Tests for tools/melee-agent/src/cli/fingerprint.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.cli.fingerprint import (
    extract_function_body,
    compute_fingerprint,
    fingerprint_for,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fingerprint"
SAMPLE_C = FIXTURES / "sample.c"


def test_extract_alpha_body_contains_loop():
    body = extract_function_body(SAMPLE_C, "fn_alpha")
    assert body is not None
    assert "for (i = 0; i < 10; i++)" in body
    assert "buttons = arg0;" in body
    # Signature must not be inside the extracted body
    assert "void fn_alpha" not in body


def test_extract_returns_none_for_unknown_function():
    assert extract_function_body(SAMPLE_C, "no_such_function") is None


def test_extract_handles_function_pointer_return_type():
    body = extract_function_body(SAMPLE_C, "fn_gamma")
    assert body is not None
    assert "return 0;" in body


def test_extract_returns_none_for_missing_file(tmp_path):
    nonexistent = tmp_path / "does_not_exist.c"
    assert extract_function_body(nonexistent, "fn_alpha") is None


def test_regex_fallback_extracts_simple_function(monkeypatch, tmp_path):
    """When tree-sitter is unavailable, regex fallback engages."""
    from src.cli import fingerprint as fp_mod
    monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)

    source = tmp_path / "simple.c"
    source.write_text(
        "void fn_simple(int x) {\n"
        "    int y = x + 1;\n"
        "    return;\n"
        "}\n"
    )
    body = fp_mod.extract_function_body(source, "fn_simple")
    assert body is not None
    assert "int y = x + 1;" in body
    assert "void fn_simple" not in body


def test_regex_fallback_returns_none_for_unknown(monkeypatch, tmp_path):
    from src.cli import fingerprint as fp_mod
    monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)

    source = tmp_path / "simple.c"
    source.write_text("void fn_simple(int x) { int y = x; }\n")
    assert fp_mod.extract_function_body(source, "no_such_function") is None


def test_regex_fallback_handles_function_pointer_param(monkeypatch, tmp_path):
    """Parameter list with nested parens (function-pointer callback)
    must not break the parenthesis balancer."""
    from src.cli import fingerprint as fp_mod
    monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)

    source = tmp_path / "fp.c"
    source.write_text(
        "void fn_cb(int (*cb)(int)) {\n"
        "    int result = cb(0);\n"
        "}\n"
    )
    body = fp_mod.extract_function_body(source, "fn_cb")
    assert body is not None
    assert "int result = cb(0);" in body


def test_regex_fallback_does_not_match_inside_other_function(monkeypatch, tmp_path):
    """If `fn_x` only appears as a call inside `fn_y` (not as a
    definition), fallback must return None — not the body of `fn_y`."""
    from src.cli import fingerprint as fp_mod
    monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)

    source = tmp_path / "multi.c"
    source.write_text(
        "void fn_y(int x) {\n"
        "    fn_x(x);\n"
        "}\n"
    )
    # fn_x is referenced but not defined → fallback must return None
    assert fp_mod.extract_function_body(source, "fn_x") is None


def test_tree_sitter_and_regex_produce_identical_raw_for_same_input(tmp_path):
    """The two extraction paths must yield identical bodies (and thus
    identical raw fingerprints) for inputs both can parse."""
    from src.cli import fingerprint as fp_mod
    source = tmp_path / "same.c"
    source.write_text(
        "void fn_same(int x) {\n"
        "    int y = x + 1;\n"
        "    return;\n"
        "}\n"
    )
    # Tree-sitter path
    body_ts = fp_mod.extract_function_body(source, "fn_same")
    # Regex path
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)
        body_regex = fp_mod.extract_function_body(source, "fn_same")
    finally:
        monkeypatch.undo()
    assert body_ts is not None
    assert body_regex is not None
    assert body_ts == body_regex


def test_compute_fingerprint_returns_two_distinct_hashes():
    body = "int y = x + 1;\nreturn y;"
    raw, norm = compute_fingerprint(body)
    assert len(raw) == 12
    assert len(norm) == 12
    # raw and norm differ on inputs with whitespace
    assert raw != norm


def test_compute_fingerprint_norm_ignores_whitespace_only_diff():
    body_a = "int y = x + 1;\nreturn y;"
    body_b = "int y=x+1; return y;"
    raw_a, norm_a = compute_fingerprint(body_a)
    raw_b, norm_b = compute_fingerprint(body_b)
    assert raw_a != raw_b
    assert norm_a == norm_b


def test_compute_fingerprint_norm_ignores_comments():
    body_a = "int y = x + 1; // adjust\nreturn y;"
    body_b = "int y = x + 1;\nreturn y;"
    _, norm_a = compute_fingerprint(body_a)
    _, norm_b = compute_fingerprint(body_b)
    assert norm_a == norm_b


def test_fingerprint_same_body_different_names_share_hash():
    """fn_alpha and fn_beta in sample.c have identical bodies; the
    extraction is per-function so the bodies are the same. Per-function
    scoping (no cross-function collisions) is enforced at LOOKUP TIME
    in tracking.find_attempt_by_fp, not at hash time."""
    fp_alpha = fingerprint_for(SAMPLE_C, "fn_alpha")
    fp_beta = fingerprint_for(SAMPLE_C, "fn_beta")
    assert fp_alpha is not None
    assert fp_beta is not None
    assert fp_alpha.raw == fp_beta.raw


def test_fingerprint_for_returns_none_on_extraction_failure():
    assert fingerprint_for(SAMPLE_C, "no_such_function") is None


def test_regex_fallback_returns_none_for_c_keyword_name(monkeypatch, tmp_path):
    """Function name that's a C keyword (e.g. 'for', 'if') must NOT match
    the body of a control-flow block in another function."""
    from src.cli import fingerprint as fp_mod
    monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)
    source = tmp_path / "loop.c"
    source.write_text(
        "void other(int n) {\n"
        "    for (int i = 0; i < n; i++) {\n"
        "        n++;\n"
        "    }\n"
        "}\n"
    )
    assert fp_mod.extract_function_body(source, "for") is None
    assert fp_mod.extract_function_body(source, "if") is None
    assert fp_mod.extract_function_body(source, "while") is None


def test_regex_fallback_returns_none_when_body_contains_string_delimiter(monkeypatch, tmp_path):
    """A `}` inside a string literal must not be treated as a closing
    brace. Conservative fallback: bail to None rather than risk a wrong body."""
    from src.cli import fingerprint as fp_mod
    monkeypatch.setattr(fp_mod._ts, "is_available", lambda: False)
    source = tmp_path / "strings.c"
    source.write_text(
        'void fn_print(int n) {\n'
        '    printf("close brace: }");\n'
        '    return;\n'
        '}\n'
    )
    assert fp_mod.extract_function_body(source, "fn_print") is None


def test_compute_fingerprint_norm_distinguishes_identifier_collisions():
    """`int x` (two tokens) and `intx` (one identifier) must NOT collide
    on the normalized hash — the word-boundary-aware normalization must
    preserve the space between word characters."""
    body_a = "int x; return x;"
    body_b = "intx;returnx;"
    _, norm_a = compute_fingerprint(body_a)
    _, norm_b = compute_fingerprint(body_b)
    assert norm_a != norm_b


def test_compute_fingerprint_norm_handles_multiline_word_boundaries():
    """Whitespace between two identifiers (single OR multiple chars,
    including newlines + indentation) must collapse to a single space,
    never to nothing. Otherwise `static const\\n    int FOO;` would
    incorrectly collapse to `static constint FOO;`."""
    body_a = "static const int FOO;"
    body_b = "static const\n    int FOO;"
    _, norm_a = compute_fingerprint(body_a)
    _, norm_b = compute_fingerprint(body_b)
    assert norm_a == norm_b  # whitespace-only diff → same hash

    # And distinct from the joined-token form
    body_c = "static constint FOO;"
    _, norm_c = compute_fingerprint(body_c)
    assert norm_a != norm_c
